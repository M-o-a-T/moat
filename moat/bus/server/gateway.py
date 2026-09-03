# noqa:D100
from __future__ import annotations

import logging

import trio

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.bus.backend import BaseBusHandler

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

    def __init__(self, serial: BaseBusHandler, mqtt: BaseBusHandler, prefix: str) -> None:
        if not mqtt.id.startswith(prefix):
            raise RuntimeError(f"My MQTT ID must start with {prefix!r}")
        self.serial: BaseBusHandler = serial
        self.mqtt: BaseBusHandler = mqtt
        self.prefix: str = prefix

    async def run(self) -> None:  # noqa:D102
        async with trio.open_nursery() as n:
            n.start_soon(self.serial2mqtt)
            n.start_soon(self.mqtt2serial)

    async def serial2mqtt(self) -> None:  # noqa:D102
        async for msg in self.serial:
            await self.mqtt.send(msg)

    async def mqtt2serial(self) -> None:  # noqa:D102
        async for msg in self.mqtt:
            if self.prefix and msg._mqtt_id.startswith(self.prefix):  # noqa:SLF001
                continue
            try:
                await self.serial.send(msg)
            except TypeError:
                logger.exception("Owch: %r", msg)
