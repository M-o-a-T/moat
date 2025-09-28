"""
Support code to connect to a TCP server.
"""

from __future__ import annotations

import anyio
import errno

from moat.micro.proto.stream import AnyioBuf
from moat.util.compat import AC_use, log


class Link(AnyioBuf):
    """
    A channel that connects to a remote TCP socket.
    """

    def __init__(self, host: str, port: int, retry: dict = {}):  # noqa:B006
        self.host = host
        self.port = port
        self.retry = retry
        # pass cfg instead!

    async def stream(self):
        """
        Open a TCP connection.
        """

        n = 0
        retry = self.retry
        sl = retry.get("delay", 0.1)
        er = None
        try:
            with anyio.fail_after(retry.get("timeout", 999)):
                while True:
                    try:
                        s = await anyio.connect_tcp(self.host, self.port)
                    except OSError as e:
                        er = e.__cause__ if e.errno is None else e
                        if er.errno not in {
                            errno.ENETUNREACH,
                            errno.EHOSTUNREACH,
                            errno.ECONNREFUSED,
                        }:
                            raise
                        if n > retry.get("attempts", 10):
                            raise TimeoutError from er
                        if n == 0:
                            log("Retrying: %s %d, %r", self.host, self.port, er)
                        n += 1
                        await anyio.sleep(sl)
                        sl *= retry.get("backoff", 1.3)
                    else:
                        if n:
                            log("Success: %s %d", self.host, self.port)
                        return await AC_use(self, s)
        except TimeoutError:
            log("Fail: %s %d, %r", self.host, self.port, er)
            raise
