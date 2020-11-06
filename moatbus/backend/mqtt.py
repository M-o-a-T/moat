
import random
from contextlib import asynccontextmanager

from distmqtt.client import open_mqttclient
from distmqtt.codecs import MsgPackCodec

from . import BaseBusHandler
from ..message import BusMessage


class MqttBusHandler(BaseBusHandler):
    _mqtt = None

    def __init__(self, id:str=None, uri:str = "mqtt://localhost/", topic="test/moat/bus"):
        super().__init__()
        if id is None:
            id = "".join(random.choices("abcdefghjkmnopqrstuvwxyz23456789", k=9))
        self.id = id
        self.uri = uri
        self.topic = topic

    @asynccontextmanager
    async def _ctx(self):
        async with open_mqttclient() as C:
            await C.connect(uri=self.uri)
            async with C.subscription(self.topic, codec=MsgPackCodec()) as CH:
                self._mqtt = CH
                yield self

    def __aiter__(self):
        self._mqtt_it = self._mqtt.__aiter__()
        return self

    async def __anext__(self):
        while True:
            msg = await self._mqtt_it.__anext__()
            try:
                msg = msg.data
            except AttributeError:
                continue
            try:
                id = msg.pop('_id')
            except KeyError:
                continue
            else:
                if id == self.id:
                    continue
                msg = BusMessage(**msg)
                msg._mqtt_id = id
                return msg

    async def send(self, msg):
        data={k:getattr(msg,k) for k in msg._attrs}
        data['_id'] = getattr(msg,'_mqtt_id',self.id)
        await self._mqtt.publish(topic=None, message=data)

