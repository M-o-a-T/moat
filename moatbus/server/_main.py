# -*- encoding: utf-8 -*-

import asyncclick as click
import trio
from anyio_serial import Serial
from contextlib import asynccontextmanager
from distmqtt.client import open_mqttclient
from distmqtt.codecs import MsgPackCodec

from .server import Server
from ..backend.stream import Anyio2TrioStream, StreamBusHandler

import logging
logger = logging.getLogger(__name__)

class MqttServer(Server):
    def __init__(self, serial, mqtt_in, topic_out):
        self.serial = serial
        self.mqtt = mqtt_in
        self.topic = topic_out
        self.bus = StreamBusHandler(serial,"Ser")

    async def reader(self):
        async with self.bus as b:
            async for msg in b:
                await self.mqtt.publish(topic=self.topic, payload=dict(
                    src=msg.src, dst=msg.dst, code=msg.code, data=msg.data.bytes,
                    ))

    async def xmit(self, src,dst,code,data):
        m=BusMessage()
        m.src=src
        m.dst=dst
        m.code=code
        m.add_data(data)
        await self.send(m)


async def run(uri='mqtt://localhost/', topic_in="/test/moat/in", topic_out="test/moat/out", server_id=1, port="/dev/ttyUSB0", baud=57600):
    async with open_mqttclient() as C:
        await C.connect(uri=uri)
        async with Serial(port=port, baudrate=baud) as S:
            S=Anyio2TrioStream(S)
            async with C.subscription(topic_in, codec=MsgPackCodec()) as CH:
                async with MqttServer(CH, topic_out) as CM:
                    async with trio.open_nursery() as n:
                        n.start_soon(S.reader)
                        async for msg in CH:
                            xmit(**msg)


@click.command("server")
@click.option("-u","--uri", default='mqtt://localhost/', help="URI of MQTT server")
@click.option("-i","--topic-in", default='/test/moat/in', help="Topic to send incoming messages to")
@click.option("-o","--topic-out", default='/test/moat/out', help="Topic to read outgoing messages from")
@click.option("-p","--port", default='/dev/ttyUSB0', help="Serial port to access")
@click.option("-b","--baud", type=int, default=57600, help="Serial port baud rate")
async def _main(**kw):
    await run(**kw)

if __name__ == "__main__":
    trio.run(_main)
