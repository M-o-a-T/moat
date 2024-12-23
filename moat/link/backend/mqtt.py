"""
A backend that talks using MQTT
"""

from __future__ import annotations

import anyio
import logging
import time
from contextlib import asynccontextmanager

from mqttproto.async_client import AsyncMQTTClient, Will

from moat.link.meta import MsgMeta
from moat.mqtt.codecs import NoopCodec
from moat.util import NotGiven, attrdict
from moat.util.path import PS, P, Path

from . import Backend as _Backend
from . import Message, RawMessage, get_codec

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.lib.codec import Codec

    from collections.abc import AsyncIterator, Awaitable


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

    client = None

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
        self.logger = logging.getLogger(__name__ + "." + self.name)

        kw = cfg.copy()
        kw.pop("driver", None)
        self.trace = kw.pop("trace", True)
        codec = kw.pop("codec", None)

        kw["client_id"] = self.name

        a = (kw.pop("host"),) if "host" in kw else ()
        self.codec = NoopCodec() if codec is None else get_codec(codec)
        self.mcodec = get_codec("std-cbor")

        will = will or kw.pop("will", None)
        if will is not None:
            data = will.pop("data", NotGiven)
            cdc = will.pop("codec", None)
            cdc = self.codec if cdc is None else get_codec(cdc)

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
        codec: str | Codec | None = None,
        raw: bool | None = False,
        **kw,
    ) -> AsyncIterator[AsyncIterator[Message]]:
        "watch a topic"

        topic = topic.slashed
        self.logger.info("Monitor %s start", topic)
        codec = self.codec if codec is None else get_codec(codec)
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
                                        val=oprop,
                                        pattern=topic,
                                        msg=repr(exc),
                                    ),
                                )
                                err = exc
                            else:
                                try:
                                    data = codec.decode(msg.payload)
                                except Exception as exc:
                                    self.logger.debug("Decoding Error", exc_info=exc)
                                    await self.send(
                                        P(":R.error.link.mqtt.codec"),
                                        dict(
                                            codec=type(codec).__name__,
                                            topic=topic,
                                            val=msg.payload,
                                            msg=repr(exc),
                                        ),
                                    )
                                    err = exc
                                else:
                                    # everything OK
                                    if self.trace:
                                        self.logger.info("R:%s %r", topic, data)
                                    yield Message(topic, data, prop, msg)
                                continue
                        if raw is False:
                            # don't forward undecodeable messages
                            continue
                        if self.trace:
                            self.logger.info("R:%s R|%r", topic, msg.payload)
                        yield RawMessage(topic, msg.payload, prop, msg, exc=err)

                yield sub_get(sub)
        except anyio.get_cancelled_exc_class():
            raise
        except BaseException as exc:
            self.logger.exception("Monitor %s end", topic, exc_info=exc)
            raise
        else:
            self.logger.info("Monitor %s end", topic)

    def send(
        self,
        topic,
        payload,
        codec: Codec | str | None = None,
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
        if codec is None:
            codec = self.codec
        elif isinstance(codec, str):
            codec = get_codec(codec)
        msg = codec.encode(payload)

        if self.trace:
            self.logger.info("S:%s %r", topic, payload)
        return self.client.publish(
            topic.slashed,
            payload=msg,
            user_properties=prop,
            retain=retain,
            **kw,
        )
