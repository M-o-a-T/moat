from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import time
import anyio
import random
from base64 import b85encode, b85decode
from mqttproto.async_client import AsyncMQTTClient, Will
from moat.mqtt.codecs import NoopCodec
from moat.util import CtxObj, attrdict
from moat.util.path import PS
from moat.lib.codec import get_codec as _get_codec
from . import Backend as _Backend
from . import get_codec, Message, RawMessage

logger = logging.getLogger(__name__)


def get_codec(name):
    "Codec loader; replaces 'std-' prefix with 'moat.util.'"
    if name[0:4] == "std-":
        name = "moat.util."+name[4:]
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

    def __init__(self, cfg, will:attrdict|None=None, name=None):
        super().__init__(cfg, name=name)
        self.cfg = cfg
        kw = cfg.copy()
        kw.pop("driver", None)
        will = will or kw.pop("will", None)

        kw["client_id"] = self.name

        if "host" in kw:
            a = (kw.pop("host"),)
        else:
            a = ()
        codec = cfg.get("codec", None)
        self.codec = NoopCodec() if codec is None else get_codec(codec)
        self.mcodec = get_codec("std-cbor")
        if will is not None:
            data = will.pop("data", NotGiven)
            cdc = will.pop("codec", None)
            cdc = codec if cdc is None else get_codec(cdc)

            if data is NotGiven:
                data = b''
            else:
                data = b85encode(cdc.encode(data)).decode("utf-8"),
            kw["will"] = Will(
                topic = will["topic"].slashed,
                payload = data,
                qos = cfg.will.qos,
                retain = cfg.will.retain,
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
    async def monitor(self, topic, *, codec:str|Codec|None=None, qos=None, **kw):
        topic = topic.slashed
        logger.info("Monitor %s start", topic)
        if codec is None:
            codec = self.codec
        elif isinstance(codec,str):
            codec = get_codec(codec)
        try:
            async with self.client.subscribe(topic, **kw) as sub:
                async def sub_get(sub):
                    async for msg in sub:
                        try:
                            topic = PS(msg.topic)
                        except Exception as exc:
                            # XXX complain
                            await self.send(P(":R.error.moat.link.mqtt.topic"),
                                    dict(msg="Parser", val=msg.topic, pattern=topic))
                            topic = Path.build(msg.topic.split("/"))
                        prop = msg.user_properties.get("MoaT")
                        if prop:
                            # *sigh* this could have been easier
                            prop = self.mcodec.decode(b85decode(prop.encode("utf-8")))
                        else:
                            # schema._.frame
                            prop = attrdict()
                        if "timestamp" not in prop:
                            prop["timestamp"]=time.time()
                        if "origin" not in prop:
                            prop["origin"]=f"via {self.name}"
                        try:
                            yield Message(topic, codec.decode(msg.payload), prop, msg, **prop)
                        except Exception as exc:
                            logger.debug("Decoding Error")
                            yield RawMessage(topic, msg.payload, prop, msg, exc=exc, **prop)

                yield sub_get(sub)
        except anyio.get_cancelled_exc_class():
            raise
        except BaseException as exc:
            logger.exception("Monitor %s end: %r", topic, exc)
            raise
        else:
            logger.info("Monitor %s end", topic)

    def send(self, topic, payload, **kw) -> Awaitable:  # pylint: disable=invalid-overridden-method
        """
        Send this payload to this topic.

        The keyword arguments @timestamp and @origin will be used for the
        MoaT user property.
        """
        prop = attrdict()
        prop.timestamp = kw.pop("timestamp") if 'timestamp' in kw else time.time()
        prop.timestamp = kw.pop("origin") if 'origin' in kw else self.name
        prop = b85encode(self.mcodec.encode(prop)).decode("utf-8")
        return self.client.publish(topic.slashed, payload=payload, user_properties={"MoaT":prop})

