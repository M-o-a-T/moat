# -*- encoding: utf-8 -*-

import asyncclick as click
import trio
from anyio_serial import Serial
from contextlib import asynccontextmanager
from distmqtt.client import open_mqttclient
from distmqtt.codecs import MsgPackCodec

from .server import Server
from ..message import BusMessage
from ..backend.stream import Anyio2TrioStream, StreamBusHandler

import logging
logger = logging.getLogger(__name__)

class Gateway:
    """
    Transfer messages between serial MoaT and MQTT

    Parameters:
        serial: a Serial bus handler instance
        mqtt: a MQTT bus handler instance
        prefix: if the message ID starts with this it's not forwarded.
                Required to prevent loops.
    """
    def __init__(self, serial, mqtt, prefix):
        if not mqtt.id.startswith(prefix):
            raise RuntimeError("My MQTT ID must start with %r" % (prefix,))
        self.serial = serial
        self.mqtt = mqtt
        self.prefix = prefix

    async def run(self):
        async with trio.open_nursery() as n:
            n.start_soon(self.serial2mqtt)
            n.start_soon(self.mqtt2serial)

    async def serial2mqtt(self):
        async for msg in self.serial:
            await self.mqtt.send(msg)

    async def mqtt2serial(self):
        async for msg in self.mqtt:
            if self.prefix and msg._mqtt_id.startswith(self.prefix):
                continue
            try:
                await self.serial.send(msg)
            except TypeError:
                logger.exception("Owch: %r", msg)

