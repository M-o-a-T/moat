"""
Support code to connect to a TCP server.
"""

from __future__ import annotations

import asyncio
import errno
import select

from moat.micro.compat import AC_use, log
from moat.micro.proto.stream import AIOBuf

p = select.poll()


class Link(AIOBuf):
    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port

    async def stream(self):
        rs, ws = await asyncio.open_connection(self.host, self.port)
        if rs is not ws:
            RuntimeError("SingleSockOnly %r %r", rs, ws)

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
