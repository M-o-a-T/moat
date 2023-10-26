"""
Implements an alarm aggregator.

Alarms consist of a condition object, a path, and some data.
They can be raised, updated, or lowered.

The aggregator's job is to collect the alarms so that the server can poll
a single object.

Alarm conditions are subclasses of exceptions.
"""
from __future__ import annotations

from moat.util import Queue, merge

from .cmd.base import BaseCmd
from .compat import AC_use, TaskGroup

from typing import TYPE_CHECKING  # isort:skip

if TYPE_CHECKING:

    from moat.util import Path


__all__ = [
    "Alert",
    "AlertHandler",
]


class Alert(Exception):
    """Alert wrapper. The path isn't stored in it."""

    def __init__(self, data):
        self.data = data


class AlertIter:
    def __init__(self, ah: AlertHandler, s: bool):
        self.ah = ah
        self.s = s

    async def __aenter__(self):
        if self.ah._q is not None:  # noqa:SLF001
            raise RuntimeError("already on")
        self.ah._q = Queue(10)  # noqa:SLF001
        self.xal = iter(list(self.ah.alarms.items()))
        return self

    async def __aexit__(self, *tb):
        self.ah._q = None  # noqa:SLF001

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
            a, p, d = await self.ah._q.get()  # noqa:SLF001
        res = {"a": a, "p": p}
        if d is not None:
            res["d"] = d
        return res


class AlertHandler(BaseCmd):
    """
    Collect open alerts.

    This helper class keeps track of open alerts and lets multiple clients
    receive them.

    This command can pull + redistribute alerts from satellites::

        apps:
          al: link.Alert
          r: …
        al:
          pull:
          - rem: !P r
            al: !P a
        r:
          cfg:
            a: link.Alert

    The rem/al split is used because incoming alert paths are prefixed with
    the "rem" path so that the destination is known and unique.
    """

    _q: Queue = None

    def __init__(self, cfg):
        super().__init__(cfg)
        self.alarms: dict[tuple[type[Alert], Path], Alert] = {}
        self._pull = {}

    async def setup(self):  # noqa:D102
        await super().setup()
        await self._start_pull()

    async def _rdr(self, p):
        rem = p["rem"]
        al = p["al"]
        async with self.root.send_iter(*rem, *al) as it:
            async for res in it:
                await self.cmd_w(a=res["a"], p=rem + res["p"], d=res.get("d", None))

    async def _start_pull(self):
        if (pl := self.cfg.get("pull", None)) is not None:
            if getattr(self, "tg", None) is None:
                self.tg = await AC_use(self, TaskGroup())

            for p in pl:
                self._pull[p] = await self.tg.spawn(self._rdr, p)
        else:
            pl = {}

        for k, v in list(self._pull):
            if k not in pl:
                v.cancel()
                del self._pull[k]

    async def reload(self):  # noqa:D102
        await self._start_pull()

    def iter_r(self, s: bool = False):
        """read open alarms.

        If @s is True, send a snapshot.
        Otherwise iterate for new alerts.
        """
        return AlertIter(self, s)

    async def cmd_w(self, a: type[Alert], p: Path, d: dict|None = None):
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
            self.alarms[k] = a(d)
        else:
            if d is not None:
                merge(al.data, d)
            else:
                del self.alarms[k]

        if self._q is not None:
            self._q.put((a, p, d))
