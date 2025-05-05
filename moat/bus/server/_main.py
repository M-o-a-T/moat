"""
This code implements a transfer service that shuffles messages from the MoaT
bus to MQTT.
"""

from __future__ import annotations

import asyncclick as click
from anyio_serial import Serial
from moat.link.backend.mqtt import Backend
from moat.util.msgpack import StdMsgpack

from .server import Server
from moat.bus.backend.stream import Anyio2TrioStream, StreamBusHandler

import logging

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
    topic_in="test/moat/in",
    topic_out="test/moat/out",
    server_id=1,
    port="/dev/ttyUSB0",
    baud=57600,
):
    async with open_mqttclient(dict(host="localhost", codec=StdMsgpack())) as C:
        async with Serial(port=port, baudrate=baud) as S:
            async with C.monitor(topic_in, codec=StdMsgpack()) as CH:
                async with MqttServer(S, CH, topic_out) as CM:
                    async with anyio.create_task_group() as n:
                        n.start_soon(CM.reader)
                        async for msg in CH:
                            logger.debug("OUT: %r", msg.data)
                            await CM.send(**msg.data)


@cli.command("server")
@click.option("-u", "--uri", default="mqtt://localhost/", help="URI of MQTT server")
@click.option(
    "-i",
    "--topic-in",
    default="test/moat/in",
    help="Topic to send incoming messages to",
)
@click.option(
    "-o",
    "--topic-out",
    default="test/moat/out",
    help="Topic to read outgoing messages from",
)
@click.option("-p", "--port", default="/dev/ttyUSB0", help="Serial port to access")
@click.option("-b", "--baud", type=int, default=57600, help="Serial port baud rate")
@click.option("-d", "--debug", is_flag=True, help="Debug?")
async def _main(debug, **kw):
    """
    Simple message transfer from MQTT to MoaT-bus-serial and back.
    """
    logging.basicConfig(level=logging.DEBUG if debug else logging.WARNING)
    l = logging.getLogger("distmqtt.mqtt.protocol.handler")
    l.setLevel(logging.INFO)
    l = logging.getLogger("transitions.core")
    l.setLevel(logging.WARNING)
    await run(**kw)
