"""
Apps used for testing.
"""

from __future__ import annotations

import sys

from moat.lib.cmd.errors import NoStream
from moat.micro.cmd.base import BaseCmd
from moat.util.compat import Event, L, Queue, log, sleep_ms, wait_for_ms

# Typing
from typing import TYPE_CHECKING  # isort:skip

if TYPE_CHECKING:
    from moat.lib.cmd import Msg

    from collections.abc import Awaitable
    from typing import Any


class Cmd(BaseCmd):
    """
    A rather basic test command.
    """

    n = 0
    err: Exception = None
    err_evt: Event = None

    doc_echo = dict(_d="Echo. Returns 'm'", m="any", _r=dict(r="any:m"))

    async def cmd_echo(self, m: Any):
        "Basic echo method, returns @m as ``result['r']``"
        return {"r": m}

    doc_it = dict(_d="Iterator. Sends 0…lim-1.", lim="int:limit", _o="int", delay="float:timer")

    async def stream_it(self, msg: Msg):
        "Streams numbers."
        lim = msg.get("lim", -1)
        i = 0
        d = int(msg.get("delay", 0.1) * 1000)
        async with msg.stream_out() as s:
            while i != lim:
                await sleep_ms(d)
                try:
                    await s.send(i)
                except NoStream:
                    break
                i += 1

    doc_nit = dict(_d="Call counter.", lim="int:limit", delay="float:timer")

    async def cmd_nit(self, delay: float = 0):
        "A non-iterator counter; simply counts calls to it."
        self.n += 1
        d = int(delay * 1000)
        await sleep_ms(d)
        return self.n

    doc_clr = dict(_d="Clear the counter.", n="int:new value, default zero")

    async def cmd_clr(self, n: int = 0):
        self.n = n

    doc_print = dict(_d="print string", _0="str:output", e="bool:use stderr")

    async def cmd_print(self, d: str, e: bool = False):
        "print to stdout/stderr"
        print(d, file=sys.stderr if e else sys.stdout)

    doc_error = dict(_d="raise exc", e="exc:raised")

    async def cmd_error(self, e: Exception = RuntimeError):
        "return an exception"
        if isinstance(e, Exception):
            raise e
        else:
            raise e("UserCrash")

    doc_crash = dict(_d="cause a crash", e="exc:raised")

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

    doc_rd = dict(_d="read console data")

    def cmd_rd(self) -> Awaitable:
        return self.q.get()

    async def task(self):
        if L:
            self.set_ready()
        await self.con.cmd("rdy_")

        buf = bytearray(200)
        d = 0
        while True:
            timed = False
            try:
                if d:
                    b = await wait_for_ms(200, self.con.crd, n=len(buf) - d)
                else:
                    b = await self.con.crd(n=len(buf))
            except TimeoutError:
                timed = True
            else:
                buf[d : d + len(b)] = b
                d += len(b)
            if d == len(buf) or (d > 0 and (timed or buf[d - 1] == 10)):  # lf
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
