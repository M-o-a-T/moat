"""
Support code to connect to a Unix socket.
"""

from __future__ import annotations

import anyio
import errno

from moat.lib.micro import AC_use, log
from moat.lib.stream import AnyioBuf

# Typing

from typing import TYPE_CHECKING  # isort:skip

if TYPE_CHECKING:
    from moat.lib.path import Path


class UnixLink(AnyioBuf):
    """
    A channel that connects to a remote Unix socket.
    """

    def __init__(self, port: str | Path, retry: dict | None = None):
        self.port = port
        if retry is None:
            retry = {}
        self.retry = retry

    async def stream(self):  # noqa:D102
        retry = self.retry
        sl = retry.get("delay", 0.1)
        er = None
        n = 0
        try:
            with anyio.fail_after(retry.get("timeout", 999)):
                while True:
                    try:
                        s = await anyio.connect_unix(self.port)
                    except OSError as e:
                        er = e.__cause__ if e.errno is None else e
                        if er.errno not in {
                            errno.ENOENT,
                            errno.ECONNREFUSED,
                        }:
                            raise
                        if n > retry.get("attempts", 10):
                            raise TimeoutError from er
                        if n == 0:
                            log("Retrying: %s, %r", self.port, er)
                        n += 1
                        await anyio.sleep(sl)
                        sl *= retry.get("backoff", 1.3)
                    else:
                        if n:
                            log("Success: %s", self.port)
                        return await AC_use(self, s)

        except TimeoutError:
            log("Fail: %s, %r", self.port, er)
            raise
