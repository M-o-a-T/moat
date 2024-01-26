"""
Support code to connect to a TCP server.
"""

from __future__ import annotations

import anyio

from moat.micro.compat import AC_use
from moat.micro.proto.stream import AnyioBuf


class Link(AnyioBuf):
    """
    A channel that connects to a remote TCP socket.
    """

    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port

    async def stream(self):
        """
        Open a TCP connection.

        TODO make reconnect behavior on ECONNREFUSED configurable
        """

        n = 0
        sl = 0.1
        while True:
            try:
                s = await anyio.connect_tcp(self.host, self.port)
            except OSError as e:
                if not isinstance(e, ConnectionRefusedError) and not isinstance(
                    e.__cause__,
                    ConnectionRefusedError,
                ):
                    raise
                if n > 10:
                    raise
                n += 1
                await anyio.sleep(sl)
                sl *= 1.3
            else:
                return await AC_use(self, s)
