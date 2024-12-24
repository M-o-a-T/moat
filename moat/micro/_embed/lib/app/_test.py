"""
Apps used for testing.
"""

from __future__ import annotations

import sys

from moat.micro.cmd.base import BaseCmd
from moat.micro.compat import Event, L, Queue, log, wait_for_ms

# Typing
from typing import TYPE_CHECKING  # isort:skip

if TYPE_CHECKING:
    from typing import Any
    from collections.abc import Awaitable


class Cmd(BaseCmd):
    """
    A rather basic test command.
    """

    n = 0
    err: Exception = None
    err_evt: Event = None

    async def cmd_echo(self, m: Any):
        "Basic echo method, returns @m as ``result['r']``"
        return {"r": m}

    def iter_it(self, lim: int | None = None):
        "returns a `NumIter`"
        return NumIter(lim)

    async def cmd_nit(self, lim: int | None = None):
        "A non-iterator counter; simply counts calls to it."
        self.n += 1
        if lim is not None and self.n > lim:
            raise StopAsyncIteration
        return self.n

    async def cmd_clr(self, n: int = 0):
        self.n = n

    async def cmd_print(self, d: str, e: bool = False):
        "print to stdout/stderr"
        print(d, file=sys.stderr if e else sys.stdout)

    async def cmd_error(self, e: Exception = RuntimeError):
        "return an exception"
        if isinstance(e, Exception):
            raise e
        else:
            raise e("UserCrash")

    async def cmd_crash(self, e: Exception = RuntimeError, a=("UserCrash",)):
        "raise an exception"
        if isinstance(e, Exception):
            self.err = e
        else:
            self.err = e(*a)
        self.err_evt.set()

    async def setup(self):
        self.err_evt = Event()
        await super().setup()

    async def task(self):
        if L:
            self.set_ready()
        await self.err_evt.wait()
        raise self.err


class Cons(BaseCmd):
    """
    A console reader.

    Config:

        cons: path to the *Blk / *Msg reading the data
        lines: max lines to queue up
        prefix: log prefix.

    """

    def __init__(self, cfg):
        super().__init__(cfg)

    async def setup(self):
        await super().setup()
        self.con = self.root.sub_at(self.cfg["cons"])
        if self.cfg.get("prefix", None) is None:
            self.q = Queue(self.cfg.get("lines", 10))

    def cmd_rd(self) -> Awaitable:
        return self.q.get()

    async def task(self):
        if L:
            self.set_ready()
        buf = bytearray(200)
        d = 0
        while True:
            timed = False
            try:
                if d:
                    b = await wait_for_ms(200, self.con.crd, n=len(buf) - d)
                else:
                    b = await self.con("!crd", n=len(buf))
            except TimeoutError:
                timed = True
            else:
                buf[d : d + len(b)] = b
                d += len(b)
            if d == len(buf) or d > 0 and (timed or buf[d - 1] == 10):  # lf
                p = self.cfg.get("prefix", None)
                if p is None:
                    self.q.put(buf[:d])
                else:
                    log(
                        "%s: %s",
                        p,
                        str(memoryview(buf)[: d - (buf[d - 1] == 10)], "utf-8"),
                    )
                d = 0


class NumIter:
    """
    A test iterator that mimics ``range(0,‹lim›)``.
    """

    def __init__(self, lim=None):
        self.lim = lim
        self.n = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *tb):
        pass

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.lim is not None and self.n >= self.lim:
            raise StopAsyncIteration
        n = self.n
        self.n += 1
        return n
