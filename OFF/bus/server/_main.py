# -*- encoding: utf-8 -*-

import logging
from contextlib import asynccontextmanager

import asyncclick as click
import trio
from anyio_serial import Serial
from distmqtt.client import open_mqttclient
from distmqtt.codecs import MsgPackCodec

from ..backend.stream import Anyio2TrioStream, StreamBusHandler
from ..message import BusMessage
from .server import Server

logger = logging.getLogger(__name__)


class MqttServer(Server):
    def __init__(self, serial, mqtt_in, topic_out):
        self.serial = serial
        self.mqtt = mqtt_in
        self.topic = topic_out
        self.bus = StreamBusHandler(serial, "Ser")
        super().__init__(self.bus)

    async def reader(self):
        async with self.bus as b:
            logger.debug("Reader started")
            async for msg in b:
                logger.debug("IN: %r", msg)
                await self.mqtt.publish(
                    topic=self.topic,
                    message=dict(
                        src=msg.src,
                        dst=msg.dst,
                        code=msg.code,
                        data=msg.data,
                    ),
                )


async def run(
    uri='mqtt://localhost/',
    topic_in="test/moat/in",
    topic_out="test/moat/out",
    server_id=1,
    port="/dev/ttyUSB0",
    baud=57600,
):
    async with open_mqttclient() as C:
        await C.connect(uri=uri)
        async with Serial(port=port, baudrate=baud) as S:
            S = Anyio2TrioStream(S)
            async with C.subscription(topic_in, codec=MsgPackCodec()) as CH:
                async with MqttServer(S, CH, topic_out) as CM:
                    async with trio.open_nursery() as n:
                        n.start_soon(CM.reader)
                        async for msg in CH:
                            logger.debug("OUT: %r", msg.data)
                            await CM.send(**msg.data)


@click.command("server")
@click.option("-u", "--uri", default='mqtt://localhost/', help="URI of MQTT server")
@click.option(
    "-i", "--topic-in", default='test/moat/in', help="Topic to send incoming messages to"
)
@click.option(
    "-o", "--topic-out", default='test/moat/out', help="Topic to read outgoing messages from"
)
@click.option("-p", "--port", default='/dev/ttyUSB0', help="Serial port to access")
@click.option("-b", "--baud", type=int, default=57600, help="Serial port baud rate")
@click.option("-d", "--debug", is_flag=True, help="Debug?")
async def _main(debug, **kw):
    logging.basicConfig(level=logging.DEBUG if debug else logging.WARNING)
    l = logging.getLogger("distmqtt.mqtt.protocol.handler")
    l.setLevel(logging.INFO)
    l = logging.getLogger("transitions.core")
    l.setLevel(logging.WARNING)
    await run(**kw)


if __name__ == "__main__":
    trio.run(_main)
