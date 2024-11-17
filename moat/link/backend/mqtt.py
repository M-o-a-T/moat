from __future__ import annotations

import anyio
import logging
import time
from contextlib import asynccontextmanager

from mqttproto.async_client import AsyncMQTTClient, Will

from moat.lib.codec import Codec
from moat.lib.codec import get_codec as _get_codec
from moat.mqtt.codecs import NoopCodec
from moat.util import attrdict
from moat.util.path import PS

from ..meta import MsgMeta
from . import Backend as _Backend
from . import Message, RawMessage, get_codec

logger = logging.getLogger(__name__)


def get_codec(name: str | Codec) -> Codec:
    "Codec loader; replaces 'std-' prefix with 'moat.util.'"
    if isinstance(name, Codec):
        return name
    if name[0:4] == "std-":
        name = "moat.util." + name[4:]
    return _get_codec(name)


class MqttMessage:
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

    def __init__(self, cfg, will: attrdict | None = None, name=None, meta: bool = True):
        """
        Connect to MQTT.

        @cfg: at moat.link.backend
        @meta: if set (the default), always attach metadata when sending.
        @will: topic+data+retain+qos+codec for on-death message

        """
        super().__init__(cfg, name=name)
        self.cfg = cfg
        self.meta = meta

        kw = cfg.copy()
        kw.pop("driver", None)
        codec = kw.pop("codec", None)

        kw["client_id"] = self.name

        if "host" in kw:
            a = (kw.pop("host"),)
        else:
            a = ()
        self.codec = NoopCodec() if codec is None else get_codec(codec)
        self.mcodec = get_codec("std-cbor")

        will = will or kw.pop("will", None)
        if will is not None:
            data = will.pop("data", NotGiven)
            cdc = will.pop("codec", None)
            cdc = codec if cdc is None else get_codec(cdc)

            if data is NotGiven:
                data = b""
            else:
                data = cdc.encode(data)
            kw["will"] = Will(
                topic=will["topic"].slashed,
                payload=data,
                qos=will.get("qos", 1),
                retain=will.get("retain", False),
            )
        self.a, self.kw = a, kw

    @asynccontextmanager
    async def connect(self):
        async with AsyncMQTTClient(*self.a, **self.kw) as self.client:
            try:
                yield self
            finally:
                self.client = None

    @asynccontextmanager
    async def monitor(
        self, topic, *, codec: str | Codec | None = None, qos=None, raw: bool | None = False, **kw
    ) -> AsyncIterator[AsyncIterator[Message]]:
        topic = topic.slashed
        logger.info("Monitor %s start", topic)
        codec = self.codec if codec is None else get_codec(codec)
        try:
            async with self.client.subscribe(topic, **kw) as sub:

                async def sub_get(sub) -> AsyncIterator[Message]:
                    async for msg in sub:
                        err = None
                        try:
                            topic = PS(msg.topic)
                        except Exception as exc:
                            # XXX complain
                            await self.send(
                                P(":R.error.link.mqtt.topic"),
                                dict(val=msg.topic, pattern=topic, msg=repr(exc)),
                            )
                            topic = Path.build(msg.topic.split("/"))

                        prop = oprop = msg.user_properties.get("MoaT")
                        if not raw:
                            try:
                                prop = oprop = msg.user_properties.get("MoaT")
                                if prop:
                                    prop = MsgMeta.decode(self.name, prop)
                                else:
                                    prop = MsgMeta(name=self.name)

                                assert prop.origin
                                if not prop.timestamp:
                                    prop.timestamp = time.time()

                            except Exception as exc:
                                logger.debug("Property Error", exc_info=exc)
                                await self.send(
                                    P(":R.error.link.mqtt.meta"),
                                    dict(topic=topic, val=oprop, pattern=topic, msg=repr(exc)),
                                )
                                err = exc
                            else:
                                try:
                                    data = codec.decode(msg.payload)
                                except Exception as exc:
                                    logger.debug("Decoding Error", exc_info=exc)
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
                                    yield Message(topic, data, prop, msg)
                                continue
                        if raw is False:
                            # don't forward undecodeable messages
                            continue
                        yield RawMessage(topic, msg.payload, prop, msg, exc=err)

                yield sub_get(sub)
        except anyio.get_cancelled_exc_class():
            raise
        except BaseException as exc:
            logger.exception("Monitor %s end: %r", topic, exc)
            raise
        else:
            logger.info("Monitor %s end", topic)

    def send(
        self, topic, payload, codec: Codec | str | None = None, meta: MsgMeta | bool | None = None
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
            prop["MoaT"] = MsgMeta(origin=self.name)
        elif meta is not False:
            prop["MoaT"] = meta.encode()
        if codec is None:
            codec = self.codec
        elif isinstance(codec, str):
            codec = get_codec(codec)
        payload = codec.encode(payload)

        return self.client.publish(topic.slashed, payload=payload, user_properties=prop)
