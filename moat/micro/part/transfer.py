"""
Data transfer handler.

This is intended for regularly moving data from A to B.
"""

from __future__ import annotations

from moat.util import Queue, QueueFull, combine_dict
from moat.lib.micro import Event, L, TaskGroup, every_ms, idle, is_async, log, ticks_ms
from moat.lib.path import Path
from moat.lib.rpc import BaseCmd

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.lib.path import PathElem
    from moat.lib.rpc import Msg

    from collections.abc import Awaitable, Mapping, Sequence


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
    """
    One transfer step.

    A step has an input (it's called, async) and an output (its set of queues).

    Four cases:
    - si=so=False:
      simple-call the path with incoming data
      the result is the data coming back.
      A timer or an incoming call starts the chain.
    - si=True
      Open a stream to send incoming data.
      A timer calls `cmd`.
    - so=True
      Open a stream to receive data.
      Input is sent to `cmd`, or lost. No timer.
    - si=so=True
      Input is sent to the stream and output is received from it.
      A timer may periodically run `cmd`.
    """

    call = None  # subcmd or feeder

    p: Awaitable = None
    a: tuple
    k: dict
    append: bool = False
    keep: bool = False

    t: int | None = None
    si: bool = False
    so: bool = False
    msg: Msg = None

    last_a: Sequence | None = None
    last_kw: Mapping | None = None
    _ready: Event

    def __init__(self, trans: Transfer, id: int, cfg: Path | dict):
        self.trans = trans
        self.id = id
        self.q = set()  # output queue(s)
        self._ready = Event()
        self.is_ready = self._ready.wait

        if isinstance(cfg, Path):
            p = cfg
            self.a = ()
            self.kw = {}
        else:
            p = cfg.get("p", None)
            self.a = tuple(cfg.get("a", ()))
            self.kw = cfg.get("k", {})
            self.si = cfg.get("si", self.si)
            self.so = cfg.get("so", self.so)
            self.append = cfg.get("append", self.append)
            self.keep = cfg.get("keep", self.keep)
        if p is not None:
            self.p = trans.root.sub_at(p)

    async def run(self) -> None:
        if self.p is not None:
            await self.p.rdy_()
        if self.so:
            await self.run_o()
        elif self.si:
            await self.run_i()
        else:
            await self.run_t()

    async def run_i(self) -> None:
        "Open a write-only pipe to the remote"
        async with self.p.stream_out(*self.a, **self.kw) as self.msg:
            self._ready.set()
            await self.run_t()

    async def run_o(self) -> None:
        "Open a pipe to the remote and read from it"
        async with (self.p.stream if self.si else self.p.stream_in)(*self.a, **self.kw) as msg:
            self._ready.set()
            if self.si:
                self.msg = msg
            async for m in msg:
                await self.cont(m.args, m.kw)

    async def run_t(self) -> None:
        "Run the task."
        self._ready.set()
        await idle()

    async def __call__(self, akw: tuple[list, dict] | None = None) -> tuple[list, dict] | None:
        """
        The previous step delivers data to us.
        """
        if akw is None:
            a = ()
            kw = {}
        else:
            a, kw = akw
        if self.keep:
            ra, rkw = a, kw
        if self.si:
            await self.msg.send(*a, **kw)
            return

        if self.so:
            # nothing to do
            log(f"Dropped {a} {kw}")
            pass

        if self.p is not None:
            if self.a:
                if self.append:
                    a = self.a + tuple(a)
                else:
                    a = tuple(a) + self.a
            if self.kw:
                kw = combine_dict(kw, self.kw)
            msg = await self.p.cmd((), *a, **kw)

            self.last_a = msg.args
            self.last_kw = msg.kw

            if self.keep:
                a = ra
                kw = rkw
            else:
                a = msg.args
                kw = msg.kw

        # pass on
        await self.cont(a, kw)

    async def cont(self, a, kw) -> Awaitable:
        """
        Take this data and continue to the next step
        """
        for q in self.q:
            try:
                res = q((a, kw))
                if is_async(res):
                    await res
            except QueueFull:
                pass


class Transfer(BaseCmd):
    """
    This command calls A, then calls B with the result, and so on.

    Config:
    - t: frequency at which to call A.
    - s: an array of calls.
         Either a path, or a map with
      - p: the path to use
      - a: positional arguments
      - k: keyword arguments
      - append: flag to add values at the end of a instead of in front
      - keep: flag to not replace values
      - si: Stream-in; bool, defaults to False.
      - so: Stream-out; bool, defaults to False.

      TODO: we might want a step for argument mangling

      - put: path (or list of paths) to insert data into the arguments
      - get: path (or list of paths) to extract data from the result
    """

    tg: TaskGroup
    steps: list[_Step]
    t_last: int = None

    doc = dict(
        _c=dict(
            _d="Data transfer",
            t="int:delay(ms)",
            _a=[
                dict(s="path:called"),
                dict(
                    s=dict(
                        p="path:called",
                        a="any:pos args",
                        k="any:kw args",
                        append="bool:at end?",
                        keep="bool:out only",
                        si="bool:stream in?",
                        so="bool:stream out?",
                    )
                ),
            ],
        )
    )

    def __init__(self, cfg):
        super().__init__(cfg)
        self.steps = []
        self.data = []

    async def task(self):
        "Step tasks runner"
        async with TaskGroup() as self.tg:
            for i, step in enumerate(self.cfg["s"]):
                s = _Step(self, i, step)
                if self.steps:
                    self.steps[-1].q.add(s)
                self.steps.append(s)

            for s in self.steps[::-1]:
                self.tg.start_soon(s.run)
            for s in self.steps:
                await s.is_ready()
            if L:
                self.set_ready()

            t = self.cfg.get("t", None)
            if t is None:
                await idle()
            else:
                async for _ in every_ms(t):
                    self.t_last = ticks_ms()
                    await self.steps[0]()

    async def cont(self, i, a, kw):
        "Data forwarding"
        self.data[i] = (a, kw)
        i += 1
        if i < len(self.data):
            s = self.steps[i]
            if not s.si:
                await s(a, kw)

    doc_w = dict(_d="data", qs="int:dest step (default first)", _s=True)

    async def stream_w(self, msg: Msg):
        "send data to (first) step"
        kw = msg.kw
        s0 = self.steps[kw.pop("qs", 0)]
        if msg.can_stream:
            async with msg.stream_in() as md:
                async for m in md:
                    await s0(m.a, m.kw)
        else:
            await s0(msg.a, kw)

    doc_r = dict(
        _d="data monitor",
        qs="int:src step (last)",
        cur="bool:get current value if present",
        _s=True,
    )

    async def stream_r(self, msg: Msg):
        "read data from (last) step"
        s0 = self.steps[msg.get("qs", -1)]
        q = Queue(1)
        qp = q.put
        s0.q.add(qp)
        try:
            if msg.can_stream:
                async with msg.stream_out(*(s0.last_a or ()), **(s0.last_kw or {})) as md:
                    if s0.last_a is not None and msg.get("cur", False):
                        await md.send(*s0.last_a, **s0.last_kw)
                    async for a, kw in q:
                        await md.send(*a, **kw)
            else:
                if s0.last_a is not None and msg.get("cur", False):
                    a, kw = s0.last_a, s0.last_kw
                else:
                    a, kw = await q.get()
                await msg.result(*a, **kw)
        finally:
            s0.q.remove(qp)

    doc_s = dict(_d="send state", _o="any")

    async def stream_s(self, msg: Msg):
        "feed current state"
        async with msg.stream_out(t=self.t_last) as md:
            for a, kw in self.data:
                await md.send(*a, **kw)

    async def handle(self, msg: Msg, rpath: list[PathElem]):
        "Intercept qs"
        if rpath and isinstance(rpath[-1], int):
            msg.kw["qs"] = rpath.pop()
        await super().handle(msg, rpath)
