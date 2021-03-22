
import random
from contextlib import asynccontextmanager

from distmqtt.client import open_mqttclient
from distmqtt.codecs import MsgPackCodec
from distkv.util import NotGiven, P

from moatbus.backend import BaseBusHandler
from moatbus.message import BusMessage


class Handler(BaseBusHandler):
    """
    This handler connects directly to MQTT. In contrast, the DistKV handler
    tunnels through DistKV.
    """
    short_help="Connect via MQTT"

    _mqtt = None

    def __init__(self, id:str, uri:str = "mqtt://localhost/", topic="test/moat/bus"):
        super().__init__()
        self.id = id
        self.uri = uri
        self.topic = topic

    PARAMS = {
        'id': (str, 'connection ID (unique!)', lambda x:len(x)>7, NotGiven, "must be at least 8 chars"),
        'uri': (str, 'MQTT broker URL', lambda x:'://' in x and not x.startswith("http"), "mqtt://localhost", "must be a Broker URL"),
        'topic': (P, 'message topic', lambda x:len(x)>1, NotGiven, "must be at least two elements"),
    }
    
    @staticmethod
    def check_config(cfg: dict):
        for k,v in cfg.items():
            if k not in ('id','uri','topic'):
                raise UnknownParamError(k)
            # TODO check more

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

