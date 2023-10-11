"""
Support code to connect to a Unix socket.
"""

from __future__ import annotations

import anyio

from moat.micro.compat import AC_use
from moat.micro.proto.stream import AnyioBuf

class Link(AnyioBuf):
    def __init__(self, port:str|Path):
        self.port = port

    async def stream(self):
        return await AC_use(self, await anyio.connect_unix(self.port))

