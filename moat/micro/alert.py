"""
Implements an alarm aggregator.

Alarms consist of a condition object, a path, and some data.
They can be raised, updated, or lowered.

The aggregator's job is to collect the alarms so that the server can poll
a single object.

Alarm conditions are subclasses of exceptions.
"""

from __future__ import annotations

from moat.util import Path, merge
from moat.util.compat import AC_use, Event, Queue, TaskGroup, WouldBlock

from .cmd.base import BaseCmd

from typing import TYPE_CHECKING  # isort:skip

if TYPE_CHECKING:
    from moat.lib.cmd import Msg

    from collections.abc import Iterator


__all__ = [
    "Alert",
    "AlertHandler",
]


class Alert(Exception):
    """Alert wrapper. The path isn't stored in it."""

    def __init__(self, data):
        self.data = data


class AlertIter:
    q: Queue = None
    xal: Iterator[tuple[tuple[type[Alert], Path], Alert]]

    def __init__(self, ah: AlertHandler, s: bool | None):
        self.ah = ah
        self.s = s

    async def __aenter__(self):
        if self.q is not None:
            raise RuntimeError("already on")
        self.q = q = Queue(10)
        self.ah.q.add(q)
        self.xal = iter(() if self.s is False else list(self.ah.alarms.items()))
        return self

    async def __aexit__(self, *tb):
        self.ah.q.discard(self.q)
        self.q = None

    def __aiter__(self):
        return self

    async def __anext__(self):
        a = None
        if self.xal is not None:
            try:
                k, al = next(self.xal)
            except StopIteration:
                self.xal = None
                if self.s:
                    raise StopAsyncIteration from None
            else:
                a, p = k
                d = al.data

        if a is None:
            try:
                a, p, d = await self.q.get()
            except EOFError:
                raise StopAsyncIteration  # noqa:B904,RUF100
        res = {"a": a, "p": p}
        if d is not None:
            res["d"] = d
        return res


class AlertHandler(BaseCmd):
    """
    Collect open alerts.

    This helper class keeps track of open alerts and lets multiple clients
    receive them.

    This command can monitor + redistribute alerts from satellites::

        apps:
          al: link.Alert
          r: …
        al:
          mon:
          - rem: !P r
            al: !P a
        r:
          cfg:
            a: link.Alert

    The rem/al split is used because incoming alert paths are prefixed with
    the "rem" path so that the destination is known and unique.
    """

    q: set[Queue] = None
    m: dict = None

    def __init__(self, cfg):
        super().__init__(cfg)
        self.alarms: dict[tuple[type[Alert], Path], Alert] = {}
        self.q = set()
        self._mon = {}

    async def setup(self):  # noqa:D102
        await super().setup()
        await self._start_mon()

    async def _rdr(self, p, evt):
        rem = p["rem"]
        al = p["al"]
        async with self.root.cmd(Path(*rem, *al, "r")).stream_in() as it:
            evt.set()
            async for res in it:
                await self.cmd_w(a=res["a"], p=rem + res["p"], d=res.get("d", None))

    async def _start_mon(self):
        if (pl := self.cfg.get("mon", None)) is not None:
            if getattr(self, "tg", None) is None:
                self.tg = await AC_use(self, TaskGroup())

            evs = []
            for k, v in pl.items():
                evt = Event()
                self._mon[k] = await self.tg.spawn(self._rdr, v, evt)
                evs.append(evt)
            for e in evs:
                await e.wait()

        else:
            pl = {}

        for k, v in list(self._mon.items()):
            if k not in pl:
                v.cancel()
                del self._mon[k]

    async def reload(self):  # noqa:D102
        await self._start_mon()

    doc_r = dict(_d="Stream curren alerts", s="bool:stop(default:wait)", _o="alert")

    async def stream_r(self, msg: Msg):
        """read open alarms.

        If @s ("static") is True, send a snapshot.
        Otherwise iterate on new alerts.
        """
        async with msg.stream_out(), AlertIter(self, msg.get("s", False)) as alit:
            async for al in alit:
                await msg.send(**al)

    doc_w = dict(_d="set alert", _0="type:class", _1="path", d="any:data, clears if missing")

    async def cmd_w(self, a: type[Alert], p: Path, d: dict | None = None):
        """
        Set an alert.

        @a: alarm class (a type, *not* an object)
        @p: path to the faulting object
        @d: data describing the current state

        If @d is `None`, the alert is cleared.
        """
        k = (a, p)
        al = self.alarms.get(k, None)
        if al is None:
            if d is None:
                return  # nothing to do
            self.alarms[k] = a(d)
        else:
            if d is not None:
                merge(al.data, d)
            else:
                del self.alarms[k]

        for q in list(self.q):
            try:
                q.put_nowait((a, p, d))
            except WouldBlock:
                self.q.discard(q)
                q.close_sender()

    doc_cl = dict(_d="close iters")

    async def cmd_cl(self):
        """
        Close all iterators of this alert handler.

        Used mainly for testing.
        """
        q, self.q = self.q, set()
        while q:
            q.pop().close_sender()
