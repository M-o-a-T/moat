"""
A gate that translates to Home Assistant
"""

from __future__ import annotations

import anyio
import logging
import time
from contextlib import asynccontextmanager

from mqttproto.async_client import AsyncMQTTClient, Will, PropertyType

from moat.link.meta import MsgMeta
from moat.lib.codec.noop import Codec as NoopCodec
from moat.util import NotGiven, attrdict, get_codec
from moat.util.path import PS, P, Path

from . import Gate as _Gate

from typing import TYPE_CHECKING, overload

if TYPE_CHECKING:
    from moat.lib.codec import Codec
    from moat.link.client import Link
    from collections.abc import AsyncIterator, Awaitable, Literal, Any


class Gate(_Gate):
    """
    The MQTT backend driver.
    """

    client:AsyncMQTTClient

    def __init__(
        self,
        cfg,
        will: attrdict | None = None,
        name: str | None = None,
        meta: bool = True,
    ):
        """
        Connect to MQTT.

        @cfg: at moat.link.backend
        @meta: if set (the default), always attach metadata when sending.
        @will: topic+data+retain+qos+codec for on-death message

        """
        super().__init__(cfg, name=name)
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
                topic=will["topic"].slashed,
                payload=data,
                qos=will.get("qos", 1),
                retain=will.get("retain", False),
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
        **kw,
    ) -> AsyncIterator[AsyncIterator[Message]]:
        "watch a topic"

        topic = topic.slashed
        if subtree:
            topic += "/#"
        self.logger.debug("Monitor %s start", topic)
        codec = self.codec if codec is NotGiven else get_codec(codec)
        try:
            async with self.client.subscribe(topic, **kw) as sub:

                async def sub_get(sub) -> AsyncIterator[Message]:
                    async for msg in sub:
                        err = None
                        try:
                            top = PS(msg.topic)
                        except Exception as exc:
                            await self.send(
                                P(":R.error.link.mqtt.topic"),
                                dict(val=msg.topic, pattern=topic, msg=repr(exc)),
                            )
                            # workaround for undecodeability
                            top = Path.build(msg.topic.split("/"))

                        prop = msg.user_properties.get("MoaT")
                        if not raw:
                            oprop = prop  # remember for error
                            try:
                                if prop:
                                    prop = MsgMeta.decode(self.name, prop)
                                else:
                                    prop = MsgMeta(name=self.name)

                                assert prop.origin
                                if not prop.timestamp:
                                    prop.timestamp = time.time()

                            except Exception as exc:
                                self.logger.debug("Property Error", exc_info=exc)
                                await self.send(
                                    P(":R.error.link.mqtt.meta"),
                                    dict(
                                        topic=top,
                                        pattern=topic,
                                        val=oprop,
                                        msg=repr(exc),
                                    ),
                                )
                                err = exc
                            else:
                                try:
                                    p_i = msg.properties.get(PropertyType.PAYLOAD_FORMAT_INDICATOR, 0)
                                    if not p_i:
                                        data = codec.decode(msg.payload)
                                    elif p_i == 1:
                                        data = msg.payload  # UTF-8
                                    else:
                                        raise ValueError("Unknown payload format {p_i}")
                                except Exception as exc:
                                    self.logger.debug("Decoding Error", exc_info=exc)
                                    await self.send(
                                        P(":R.error.link.mqtt.codec"),
                                        dict(
                                            codec=type(codec).__name__,
                                            topic=top,
                                            pattern=topic,
                                            val=msg.payload,
                                            msg=repr(exc),
                                        ),
                                    )
                                    err = exc
                                else:
                                    # everything OK
                                    if self.trace:
                                        self.logger.debug("R:%s %r", top, data)
                                    yield Message(top, data, prop, msg)
                                continue
                        if raw is False:
                            # don't forward undecodeable messages
                            continue
                        if self.trace:
                            self.logger.info("R:%s R|%r", top, msg.payload)
                        yield RawMessage(top, msg.payload, prop, msg, exc=err)

                yield sub_get(sub)
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
        retain: bool = False,
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
        retain: bool = False,
        **kw,
    ) -> Awaitable:  # pylint: disable=invalid-overridden-method
        ...

    def send(
        self,
        topic: Path,
        data: Any,
        codec: Codec | str | None | Literal[NotGiven] = NotGiven,
        meta: MsgMeta | bool | None = None,
        retain: bool = False,
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
        if meta is True:
            prop["MoaT"] = MsgMeta(origin=self.name).encode()
        elif meta is not False:
            prop["MoaT"] = meta.encode()

        if isinstance(data,str):
            msg = data  # utf-8 is pass-thru in MQTT5
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
            topic.slashed,
            payload=msg,
            user_properties=prop,
            retain=retain,
            **kw,
        )
