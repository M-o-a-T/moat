"""
A backend that talks using MQTT
"""

from __future__ import annotations

import anyio
import logging
import time
from contextlib import asynccontextmanager

from mqttproto.async_client import AsyncMQTTClient, Will, PropertyType, RetainHandling

from moat.link.meta import MsgMeta
from moat.lib.codec.noop import Codec as NoopCodec
from moat.util import NotGiven, attrdict, get_codec
from moat.util.path import PS, P, Path

from . import Backend as _Backend
from . import Message, RawMessage

from typing import TYPE_CHECKING, overload

if TYPE_CHECKING:
    from moat.lib.codec import Codec

    from collections.abc import AsyncIterator, Awaitable, Literal, Any


class MqttMessage:
    """
    Encapsulates (our view of) a message from MQTT.
    """

    def __init__(self, topic, payload, orig, **kw):
        self.topic = topic
        self.payload = payload
        self.orig = orig
        self.meta = attrdict(kw)


class Backend(_Backend):
    """
    The MQTT backend driver.
    """

    client:AsyncMQTTClient

    def __init__(
        self,
        cfg,
        will: attrdict | None = None,
        name: str | None = None,
        id: str | None = None,
        meta: bool = True,
    ):
        """
        Connect to MQTT.

        @cfg: at moat.link.backend
        @meta: if set (the default), always attach metadata when sending.
        @will: topic+data+retain+qos+codec for on-death message

        """
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
            kw["will"] = Will(
                topic=will["topic"].slashed2,
                payload=data,
                qos=will.get("qos", 1),
                retain=will.get("retain", data == b""),
            )
        self.a, self.kw = a, kw

    @asynccontextmanager
    async def connect(self):
        "connect to the server"
        async with AsyncMQTTClient(*self.a, **self.kw) as self.client:
            try:
                yield self
            finally:
                self.client = None  # noqa:PLW2901

    @asynccontextmanager
    async def monitor(
        self,
        topic,
        *,
        codec: str | Codec | None | Literal[NotGiven] = NotGiven,
        raw: bool | None = False,
        subtree: bool = False,
        mine:bool=True,
        retained:bool=True,
        **kw,
    ) -> AsyncIterator[AsyncIterator[Message]]:
        """
        Watch a topic.

        @codec: use this codec.
        @raw: don't interpret anything.
        @subtree: also monitor subtopics.
        @mine: send my own messages back to me.
        """

        if len(topic):
            tops = topic.slashed
            if subtree:
                tops += "/#"
        elif subtree:
            tops="#"
        else:
            raise ValueError("empty path")
        self.logger.debug("Monitor %s start", tops)
        codec = self.codec if codec is NotGiven else get_codec(codec)
        kw["no_local"] = not mine
        kw["retain_handling"] = RetainHandling.SEND_RETAINED if retained else RetainHandling.NO_RETAINED
        try:
            async with self.client.subscribe(tops, **kw) as sub:


                yield _SubGet(self,sub,codec,raw)
        except (anyio.get_cancelled_exc_class(), KeyboardInterrupt):
            raise
        except BaseException as exc:
            self.logger.exception("Monitor %s end", topic, exc_info=exc)
            raise
        else:
            self.logger.debug("Monitor %s end", topic)

    @overload
    def send(
        self,
        topic: Path,
        data: bytes | bytearray | memoryview,
        codec: Literal[None],
        meta: MsgMeta | bool | None = None,
        retain: bool|None = None,
        **kw,
    ) -> Awaitable:  # pylint: disable=invalid-overridden-method
        ...

    @overload
    def send(
        self,
        topic: Path,
        data: Any,
        codec: Codec | str | Literal[NotGiven] = NotGiven,
        meta: MsgMeta | bool | None = None,
        retain: bool|None=None,
        **kw,
    ) -> Awaitable:  # pylint: disable=invalid-overridden-method
        ...

    def send(
        self,
        topic: Path,
        data: Any,
        codec: Codec | str | None | Literal[NotGiven] = NotGiven,
        meta: MsgMeta | bool | None = None,
        retain: bool|None=None,
        **kw,
    ) -> Awaitable:  # pylint: disable=invalid-overridden-method
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

        if isinstance(data,str):
            msg = data  # utf-8 is pass-thru in MQTT5
        elif data is NotGiven:
            # delete
            msg = b''
        else:
            if codec is NotGiven:
                codec = self.codec
            elif codec is None:
                codec = NoopCodec()
            elif isinstance(codec, str):
                codec = get_codec(codec)
            # else codec is a Codec and used as-is
            msg = codec.encode(data)

        if self.trace:
            self.logger.info("S:%s %r", topic, data)
        return self.client.publish(
            topic.slashed2,
            payload=msg,
            user_properties=prop,
            retain=retain,
            **kw,
        )

class _SubGet:
    def __init__(self, back, sub, codec,raw):
        self.back = back
        self.sub = sub
        self.codec = codec
        self.raw = raw

    def __aiter__(self):
        return self

    async def __anext__(self):
        back=self.back
        err = None
        while True:
            msg = await anext(self.sub)
            try:
                top = PS(msg.topic)
            except Exception as exc:
                await back.send(
                    P(":R.error.link.mqtt.topic"),
                    dict(val=msg.topic, pattern=tops, msg=repr(exc)),
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
                        P(":R.error.link.mqtt.meta")+top,
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
                            data = self.codec.decode(msg.payload)
                        elif p_i == 1:
                            data = msg.payload  # UTF-8
                        else:
                            raise ValueError("Unknown payload format {p_i}")
                    except Exception as exc:
                        back.logger.warning("Decoding Error %s %s: %r %r", top,self.codec.__class__.__module__, msg.payload,exc, exc_info=exc)
                        await back.send(
                            P(":R.error.link.mqtt.codec")+top,
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
                        if back.trace:
                            back.logger.debug("R:%s %r", top, data)
                        return Message(top, data, meta=prop, prop=msg.user_properties, retain=msg.retain)
                    continue
            if self.raw is False:
                # don't forward undecodeable messages
                continue
            if back.trace:
                back.logger.info("R:%s R|%r", top, msg.payload)
            return RawMessage(top, msg.payload, meta=prop, prop=msg.user_properties, exc=err, retain=msg.retain)
