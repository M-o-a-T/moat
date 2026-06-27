"""
A backend that talks using MQTT
"""

from __future__ import annotations

import anyio
import logging
import time
from contextlib import asynccontextmanager

from moat.util import NotGiven, attrdict, srepr
from moat.lib.codec import get_codec
from moat.lib.codec.noop import Codec as NoopCodec
from moat.lib.mqtt.async_client import AsyncMQTTClient, PropertyType, RetainHandling, Will
from moat.lib.path import PS, P, Path
from moat.link.meta import MsgMeta

from . import Backend as _Backend
from . import Message, RawMessage

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from types import EllipsisType

    from moat.lib.codec import Codec

    from collections.abc import AsyncIterator


class MqttMessage:
    """
    Encapsulates (our view of) a message from MQTT.
    """

    def __init__(self, topic, payload, orig, **kw):
        self.topic = topic
        self.payload = payload
        self.orig = orig
        self.meta = attrdict(kw)


def _is_valid_mqtt_utf8(s: str) -> bool:
    """Return ``True`` iff ``s`` is a strict MQTT-5 UTF-8 payload.

    MQTT-5 brokers such as FlashMQ reject UTF-8 payloads containing any
    control character (U+0000..U+001F, U+007F..U+009F), lone surrogate
    code point, or Unicode noncharacter.  Per the standard, such payloads
    would otherwise tear down the connection.
    """
    for c in s:
        cp = ord(c)
        if cp <= 0x1F or 0x7F <= cp <= 0x9F:
            return False
        if 0xD800 <= cp <= 0xDFFF:
            return False
        if 0xFDD0 <= cp <= 0xFDEF:
            return False
        if (cp & 0xFFFF) in (0xFFFE, 0xFFFF):
            return False
    return True


class Backend(_Backend):
    """
    The MQTT backend driver.
    """

    client: AsyncMQTTClient | None

    def __init__(
        self,
        cfg: attrdict,
        will: attrdict | None = None,
        name: str | None = None,
        id: str | None = None,
        meta: bool = True,
    ) -> None:
        """
        Connect to MQTT.

        @cfg: at moat.link.backend
        @meta: if set (the default), always attach metadata when sending.
        @will: topic+data+retain+qos+codec for on-death message

        """
        if name is None:
            name = cfg.get("name", "mqtt")
        if id is None:
            id = name
        super().__init__(cfg, name=name, id=id)
        self.cfg = cfg
        self.meta = meta
        self.logger = logging.getLogger(__name__ + "." + (self.name or "‹…›"))

        kw = cfg.copy()
        sname = kw.pop("driver", "mqtt")
        self.trace = kw.pop("trace", False)
        try:
            codec = kw.pop("codec")  # intentionally no default
        except KeyError:
            raise RuntimeError(f"The {sname} backend requires a codec.") from None

        kw["client_id"] = self.name

        a = (kw.pop("host"),) if "host" in kw else ()
        self.codec = get_codec(codec)
        self.mcodec = get_codec("std-cbor")

        will = will or kw.pop("will", None)
        if will is not None:
            data = will.pop("data", NotGiven)
            cdc = will.pop("codec", NotGiven)
            cdc = self.codec if cdc is NotGiven else get_codec(cdc)

            data = b"" if data is NotGiven else cdc.encode(data)
            if not will["topic"].has_prefix:
                raise ValueError("Can't use a non-prefixed topic in Will")
            kw["will"] = Will(
                topic=(will["topic"]).slashed2,
                payload=data,
                qos=will.get("qos", 1),
                retain=will.get("retain", data == b""),
            )
        self.a, self.kw = a, kw
        self.client = None
        # Topics where we've already logged a UTF-8 problem in str payloads.
        # MQTT 5 marks ``str`` payloads with PAYLOAD_FORMAT_INDICATOR=1 and
        # strict brokers (e.g. FlashMQ) terminate the connection when the
        # bytes on the wire aren't valid UTF-8 (lone surrogates, NUL chars,
        # etc.).  We validate before publishing and skip + log offenders.
        self._bad_utf8_paths: set[Path] = set()

    @asynccontextmanager
    async def connect(self):
        "connect to the server"
        self.logger.debug("Start: %s %s", self.a, self.kw)
        async with AsyncMQTTClient(*self.a, **self.kw) as self.client:
            try:
                yield self
            finally:
                del self.client

    @asynccontextmanager
    async def monitor(
        self,
        topic: Path,
        *,
        codec: str | Codec | None | EllipsisType = NotGiven,
        raw: bool | None = False,
        subtree: bool = False,
        mine: bool = True,
        retained: bool = True,
        **kw: Any,
    ) -> AsyncIterator[AsyncIterator[Message]]:
        """
        Watch a topic.

        @codec: use this codec.
        @raw: don't interpret anything.
        @subtree: also monitor subtopics.
        @mine: send my own messages back to me.
        """

        if not topic.is_empty:
            tops = topic.slashed
            if subtree:
                tops += "/#"
        elif subtree:
            tops = "#"
        else:
            raise ValueError("empty path")
        if self.logger.isEnabledFor(logging.DEBUG):
            self.logger.debug("Monitor %s%s start", topic, ":*" if subtree else "")
        codec_obj: Codec | None
        if codec is NotGiven:
            codec_obj = self.codec
        elif codec is None:
            codec_obj = None
        else:
            codec_obj = get_codec(codec)
        kw["no_local"] = not mine
        kw["retain_handling"] = (
            RetainHandling.SEND_RETAINED if retained else RetainHandling.NO_RETAINED
        )
        assert self.client is not None
        try:
            async with self.client.subscribe(tops, **kw) as sub:
                yield _SubGet(self, sub, codec_obj, raw)
        except (anyio.get_cancelled_exc_class(), KeyboardInterrupt):
            raise
        except BaseException as exc:
            self.logger.exception("Monitor %s%s end", topic, ":*" if subtree else "", exc_info=exc)
            raise
        else:
            self.logger.debug("Monitor %s%s end", topic, ":*" if subtree else "")

    def _log_bad_utf8(self, topic: Path, data: str) -> None:
        """Log once per topic that we're dropping an unsendable str payload."""
        if topic in self._bad_utf8_paths:
            return
        self._bad_utf8_paths.add(topic)
        # Show enough of the payload to identify the offender without
        # flooding the log; ``repr`` exposes the offending escape sequences.
        snippet = repr(data[:200])
        if len(data) > 200:
            snippet = snippet[:-1] + "…" + snippet[-1]
        self.logger.error(
            "Dropping non-UTF8 payload at %s: %s (len=%d)",
            topic,
            snippet,
            len(data),
        )

    async def send(
        self,
        topic: Path,
        data: Any,
        codec: Codec | str | None | EllipsisType = NotGiven,
        meta: MsgMeta | bool | None = None,
        retain: bool | None = None,
        **kw: Any,
    ) -> None:
        """
        Send this payload to this topic.

        The keyword arguments @timestamp and @origin will be used for the
        MoaT user property.
        """
        prop = {}
        if meta is None:
            meta = self.meta
        if meta is False:
            if retain is None:
                retain = False
        else:
            if meta is True:
                meta = MsgMeta(origin=self.name)
            prop["MoaT"] = meta.encode()
        if retain is None:
            raise ValueError("Need to set whether to retain or not")

        if isinstance(data, str):
            if not _is_valid_mqtt_utf8(data):
                self._log_bad_utf8(topic, data)
                return
            msg = data  # utf-8 is pass-thru in MQTT5
        elif data is NotGiven:
            # delete
            msg = b""
        else:
            if codec is NotGiven:
                codec = self.codec
            elif codec is None:
                codec = NoopCodec()
            elif isinstance(codec, str):
                codec = get_codec(codec)
            # else codec is a Codec and used as-is
            msg = codec.encode(data)

        self.logger.debug("S %s %s %s", topic, srepr(data), meta)
        assert self.client is not None
        await self.client.publish(
            topic.slashed2,
            payload=msg,
            user_properties=prop,
            retain=retain,
            **kw,
        )


class _SubGet:
    def __init__(self, back, sub, codec, raw):
        self.back = back
        self.sub = sub
        self.codec = codec
        self.raw = raw

    def __aiter__(self):
        return self

    async def __anext__(self):
        back = self.back
        err = None
        while True:
            msg = await anext(self.sub)
            try:
                top = PS(msg.topic, scan=True)
            except Exception as exc:
                await back.send(
                    P(":R.error.link.mqtt.topic"),
                    dict(val=msg.topic, msg=repr(exc)),
                    retain=False,
                )
                # workaround for undecodeability
                top = Path.build(msg.topic.split("/"))

            prop = msg.user_properties.get("MoaT")
            if not self.raw:
                oprop = prop  # remember for error
                try:
                    if prop:
                        prop = MsgMeta.decode(back.name, prop)
                    else:
                        prop = MsgMeta(name=back.name)

                    assert prop.origin
                    if not prop.timestamp:
                        prop.timestamp = time.time()

                except Exception as exc:
                    back.logger.debug("Property Error", exc_info=exc)
                    await back.send(
                        P(":R.error.link.mqtt.meta") + top,
                        dict(
                            topic=top,
                            val=oprop,
                            msg=repr(exc),
                            retain=False,
                        ),
                    )
                    err = exc
                else:
                    try:
                        p_i = msg.properties.get(PropertyType.PAYLOAD_FORMAT_INDICATOR, 0)
                        if not p_i:
                            if self.codec is None:
                                data = msg.payload
                            else:
                                data = self.codec.decode(msg.payload)
                        elif p_i == 1:
                            data = msg.payload  # UTF-8
                        else:
                            raise ValueError("Unknown payload format {p_i}")
                    except Exception as exc:
                        back.logger.warning(
                            "Decoding Error %s %s: %r %r",
                            top,
                            self.codec.__class__.__module__,
                            msg.payload,
                            exc,
                        )
                        await back.send(
                            P(":R.error.link.mqtt.codec") + top,
                            dict(
                                codec=type(self.codec).__name__,
                                topic=top,
                                val=msg.payload,
                                msg=repr(exc),
                            ),
                            retain=False,
                        )
                        err = exc
                    else:
                        # everything OK
                        if back.logger.isEnabledFor(logging.DEBUG):
                            back.logger.debug("R %s %s %s", top, srepr(data), prop)
                        return Message(
                            top, data, meta=prop, prop=msg.user_properties, retain=msg.retain
                        )
                    continue
            if self.raw is False:
                # don't forward undecodeable messages
                continue
            if back.trace:
                back.logger.info("R:%s R|%r", top, msg.payload)
            return RawMessage(
                top, msg.payload, meta=prop, prop=msg.user_properties, exc=err, retain=msg.retain
            )
