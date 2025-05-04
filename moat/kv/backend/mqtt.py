from __future__ import annotations
import logging
from contextlib import asynccontextmanager

import anyio
from moat.mqtt.client import MQTTClient
from moat.util import NotGiven

from . import Backend

logger = logging.getLogger(__name__)


class MqttMessage:
    def __init__(self, topic, payload):
        self.topic = topic
        self.payload = payload


class MqttBackend(Backend):
    client = None

    @asynccontextmanager
    async def connect(self, *a, **kw):
        codec = kw.pop("codec", NotGiven)
        C = MQTTClient(self._tg, codec=codec)
        try:
            await C.connect(*a, **kw)
            self.client = C
            yield self
        finally:
            self.client = None
            with anyio.CancelScope(shield=True):
                await self.aclose()
                await C.disconnect()

    @asynccontextmanager
    async def monitor(self, *topic, codec=NotGiven):
        topic = "/".join(str(x) for x in topic)
        logger.info("Monitor %s start", topic)
        try:
            async with self.client.subscription(topic, codec=codec) as sub:

                async def sub_get(sub):
                    async for msg in sub:
                        yield MqttMessage(msg.topic.split("/"), msg.data)

                yield sub_get(sub)
        except anyio.get_cancelled_exc_class():
            raise
        except BaseException as exc:
            logger.exception("Monitor %s end: %r", topic, exc)
            raise
        else:
            logger.info("Monitor %s end", topic)

    def send(self, *topic, payload, **kw):  # pylint: disable=invalid-overridden-method
        """
        Send this payload to this topic.
        """
        # client.publish is also async, pass-thru
        return self.client.publish("/".join(str(x) for x in topic), message=payload, **kw)


@asynccontextmanager
async def connect(**kw):
    async with anyio.create_task_group() as tg:
        c = MqttBackend(tg)
        async with c.connect(**kw):
            yield c
