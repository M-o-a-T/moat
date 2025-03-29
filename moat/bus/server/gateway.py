from __future__ import annotations

import trio


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
            raise RuntimeError(f"My MQTT ID must start with {prefix!r}")
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
