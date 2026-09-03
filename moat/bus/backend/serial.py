#
"""
Send bus messages to a Trio stream
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from anyio_serial import Serial

from ._stream import StreamHandler

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


class Handler(StreamHandler):
    """
    This class defines the interface for exchanging MoaT messages on a
    serial line.

    Usage::

        async with moatbus.backend.serial.Handler("/dev/ttyUSB1",115200) as bus:
            async for msg in bus:
                await process(msg)
    """

    short_help = "Serial MoaT bus (P2P)"
    need_host = True

    port: str
    baudrate: int

    PARAMS = {
        "port": (str, "Port to use", lambda x: len(x) > 2, None, "too short"),
        "baudrate": (
            int,
            "Port speed",
            lambda x: 1200 <= x <= 2000000,
            115200,
            "must be between 1200 and 2MBit",
        ),
        "tick": (
            float,
            "frame timeout",
            lambda x: 0 < x < 1,
            0.1,
            "must be between 0 and 1 second",
        ),
    }

    def __init__(
        self, client: Any = None, port: str = "", baudrate: int = 115200, tick: float = 0.1
    ) -> None:
        super().__init__(client, None, tick)
        self.port = port
        self.baudrate = baudrate

    @classmethod
    def repr(cls, cfg: dict[str, Any]) -> str:
        """Render config as string."""
        return cfg["port"]

    @asynccontextmanager
    async def _ctx(self) -> AsyncIterator[Handler]:
        async with Serial(port=self.port, baudrate=self.baudrate) as S:
            self._stream = S
            async with super()._ctx():
                yield self
