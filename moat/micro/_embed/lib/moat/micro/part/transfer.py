"""
Data transfer handler.

This is intended for regularly moving data from A to B.
"""

from __future__ import annotations

from moat.util import NotGiven, Path, Queue
from moat.micro.cmd.base import BaseCmd
from moat.util.compat import TaskGroup, idle, sleep

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.lib.cmd.msg import Msg

    from collections.abc import Awaitable


class _Send:
    # A null context that delegates its .send method to the wrapped destination
    def __init__(self, dest):
        self.dest = dest

    def send(self, *a, **kw):
        return self.dest(*a, **kw)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *tb):
        return None


class _Step:
    # One transfer step.
    # Four cases:
    # - si=so=False:
    #   simple-call the path with incoming data
    #   the result is the data coming back.
    # - si=True
    #   Open a stream to send incoming data.
    #   A timer calls `cmd`, the result
    # - so=True
    #   Open a stream to receive data.
    #   Input is sent to `cmd`, or lost. No timer.
    # - si=so=True
    #   Input is sent to the stream and output is received from it.
    #   A timer may periodically run `cmd`.

    call = None  # subcmd or feeder

    p = None
    pcmd = None
    a: tuple
    k: dict
    app: bool = False

    t: int | None = None
    si: bool = False
    so: bool = False
    msg: Msg = None

    def __init__(self, t: Transfer, id: int, cfg: Path | dict):
        self.trans = t
        self.id = id
        self.q = set()  # output queue(s)
        if isinstance(cfg, Path):
            self.p = cfg
        else:
            self.p = cfg.get("p", None)
            self.pcmd = cfg.get("cmd", None)
            self.si = cfg.get("si", self.si)
            self.so = cfg.get("so", self.so)
            self.app = cfg.get("app", self.app)
            self.t = cfg.get("t", self.t)

    async def task(self):
        if self.so:
            await self.run_o()
        elif self.si:
            await self.run_i()
        else:
            await self.run_t()

    async def run_i(self):
        "Open a write-only pipe to the remote"
        async with self.root.stream_out(self.p, *self.a, **self.k) as self.msg:
            await self.run_t()

    async def run_o(self):
        "Open a pipe to the remote and read from it"
        async with (self.root.stream if self.si else self.root.stream_in)(
            self.p, *self.a, **self.k
        ) as msg:
            async for m in msg:
                await self.cont(self.id, m.a, m.kw)

    async def run_t(self):
        "Run the timer."
        if not self.t:
            return await idle()
        while True:
            if self.p is None:
                await self.cont(self.id, self.a, self.kw)
            else:
                msg = await self.root.cmd(self.p, *self.a, **self.kw)
                if not self.so:
                    await self.cont(self.id, msg.a, msg.kw)
            await sleep(self.t)

    async def __call__(self, a: list, kw: dict) -> tuple[list, dict] | None:
        if self.si:
            await self.msg.send(*a, **kw)
            return

        if self.p is not None:
            msg = await self.root.cmd(self.p, *a, **kw)
            if not self.so:
                await self.cont(self.id, msg.a, msg.kw)
        elif not self.so:
            await self.cont(self.id, a, kw)

    async def cont(self, a, kw) -> Awaitable:
        for q in self.q:
            await q((a, kw))


class Transfer(BaseCmd):
    """
    This command calls A, then calls B with the result, and so on.

    Config:
    - t: frequency at which to call A.
    - s: an array of calls.
         Either a path, or a map with
      - p: the path to use
      - cmd: auxiliary command for asymmetric streams
      - a: positional arguments
      - k: keyword arguments
      - si: Stream-in; bool, defaults to False.
      - so: Stream-out; bool, defaults to False.
      - app: Flag whether to append incoming positional arguments.
             If False (the default), they're prepended.
    """

    def __init__(self, cfg):
        super().__init__(cfg)
        self.steps = []
        self.data = []

    async def task(self):
        "Step tasks runner"
        async with TaskGroup() as tg:
            for i, step in enumerate(self.cfg.s):
                s = _Step(i, step)
                self.steps.append(s)
                self.data.append(NotGiven)

            for s in self.steps[::-1]:
                tg.start_soon(s.run)

    async def cont(self, i, a, kw):
        "Data forwarding"
        self.data[i] = (a, kw)
        i += 1
        if i < len(self.data):
            s = self.steps[i]
            if not s.si:
                await s(a, kw)

    doc_w = dict(_d="data", qs="int:position (default zero)")

    async def stream_w(self, msg: Msg):
        "send data to (first) step"
        kw = msg.kw
        s0 = self.steps[kw.pop("qs", 0)]
        if msg.can_stream():
            async with msg.stream_in() as md:
                async for m in md:
                    await s0(m.a, m.kw)
        else:
            await s0(msg.a, kw)

    doc_r = dict(_d="data monitor", qs="int:position (default last)")

    async def stream_r(self, msg: Msg):
        "read data from (last) step"
        s0 = self.steps[msg.get("qs", -1)]
        q = Queue(1)
        qp = q.put
        s0.q.add(qp)
        try:
            if msg.can_stream():
                async with msg.stream_out() as md:
                    async for a, kw in q:
                        await md.send(*a, **kw)
            else:
                a, kw = await q.get()
                await md.result(*a, **kw)
        finally:
            s0.q.remove(qp)

    doc_s = dict(_d="send state", _o="any")

    async def stream_s(self, msg: Msg):
        "feed current state"
        async with msg.stream_out() as md:
            async for a, kw in self.data:
                await md.send(*a, **kw)
