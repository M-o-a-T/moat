"""
Support code to connect to a TCP server.
"""

from __future__ import annotations

import select

import asyncio

from moat.micro.proto.stream import AIOBuf
from moat.util.compat import AC_use, log, sleep, wait_for

p = select.poll()


class Link(AIOBuf):
    """
    A channel that connects to a remote TCP socket.
    """

    def __init__(self, host: str, port: int, retry={}):  # noqa:B006
        self.host = host
        self.port = port
        self.retry = retry  # not changed by us
        # TODO pass the config instead of the "retry" thing

    async def stream(self):  # noqa:D102
        retry = self.retry

        async def _conn1():
            rs, ws = await asyncio.open_connection(self.host, self.port)
            if rs is not ws:
                raise RuntimeError(f"SingleSockOnly {rs!r} {ws!r}")

            # This dance is required because open_connection doesn't check
            p.register(rs.s, select.POLLIN)
            try:
                for x in p.poll(0):
                    if x[1] & (select.POLLHUP | select.POLLERR):
                        try:
                            rs.s.read(1)  # raises the applicable error
                            raise EOFError  # instead, if it's closed
                        finally:
                            rs.close()
            finally:
                p.unregister(rs.s)

            await AC_use(self, rs.close)
            return rs

        async def _conn():
            n = 0
            sl = retry.get("delay", 0.1)
            while True:
                try:
                    s = await _conn1()
                except OSError as e:
                    if n == 0:
                        log("Retrying: %s %d, %r", self.host, self.port, e)
                    n += 1
                    if n > retry.get("attempts", 10):
                        raise TimeoutError
                    await sleep(sl)
                    sl *= retry.get("backoff", 1.3)
                else:
                    if n:
                        log("Success: %s %d", self.host, self.port)
                    return s

        try:
            return await wait_for(retry.get("timeout", 99), _conn)
        except TimeoutError:
            log("Fail: %s %d", self.host, self.port)
            raise
