"""
Support code to connect to a TCP server.
"""

from __future__ import annotations
from moat.micro.compat import AC_use
from moat.micro.proto.stream import AnyioBuf

class Link(AnyioBuf):
    def __init__(self, host:str, port:int):
        self.host = host
        self.port = port

    async def stream(self):
        return await AC_use(await anyio.connect_tcp(self.host, self.port))

