"""
Support code to connect to a Unix socket.
"""

from __future__ import annotations

import anyio

from moat.micro.proto.stream import AnyioBuf
from moat.util.compat import AC_use, log

# Typing

from typing import TYPE_CHECKING  # isort:skip

if TYPE_CHECKING:
    from moat.util import Path


class Link(AnyioBuf):
    """
    A channel that connects to a remote TCP socket.
    """

    def __init__(self, port: str | Path):
        self.port = port

    async def stream(self):  # noqa:D102
        try:
            return await AC_use(self, await anyio.connect_unix(self.port))
        except Exception:
            log("Trying to connect to %r", self.port)
            raise
