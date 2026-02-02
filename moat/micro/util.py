"""
Non-embedded helpers, mainly for the command interpreter
"""

from __future__ import annotations

import hashlib

from moat.lib.micro import Event, sleep_ms
from moat.lib.rpc import BaseCmd

from ._util import del_p, get_p, set_p
from .files import APath, copytree

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.lib.rpc import Msg
    from moat.micro.files import MoatPath

    from collections.abc import Awaitable, Callable
    from typing import ClassVar

__all__ = ["Repeater", "Sensor", "del_p", "get_p", "hash256", "run_update", "set_p"]


def hash256(data):
    "Hash a chunk of bytes the way git does"
    h = hashlib.sha256()
    h.update(data)
    return h.digest()


async def _rd(f):
    "return file contents"
    async with await f.open("rb") as fd:
        return await fd.read()


async def run_update(*a, **kw):
    """
    Update a remote file system.

    The satellite contains a list of hashes for its modules.

    Thus if the source of that frozen file is identical to what we have
    now, the remote shouldn't have that file (or its .mpy derivative) in
    its file system. It might however be there as a left-over artefact from
    a previous online update. Thus we delete it.
    """
    import moat.micro._embed.lib as emb  # noqa: PLC0415

    for p in emb.__path__:
        src = APath(p)
        await _run_update(src, *a, **kw)


async def _run_update(src, dest: MoatPath, check=None, cross=None, hash_fn=None):
    # update a single _embed/lib directory

    async def drop(dst):
        """
        delete files on the satellite that didn't change between the
        version in their firmware and our current version.
        """
        # rp = dst.relative_to(emb_r)
        if dst.name == "manifest.py":
            return None

        # assume dst is relative
        sp = src.parent / dst
        # XXX we might want to ask git which files differ,
        # it's supposed to have a cache for that
        dn = str(dst)[:-3].replace("/", ".").lstrip(".")
        dn = dn.removeprefix("lib.")
        dn = dn.removesuffix(".__init__")
        try:
            res = await hash_fn(dn)
            if res is None:
                return False
        except (ImportError, KeyError):
            return False
        rs = await _rd(sp)
        return res == hash256(rs)[: len(res)]

    await copytree(src, dest, check=check, drop=drop, cross=cross)


class Repeater:
    """
    Support repeating a measurement.

    Parameters:
        min(float): Minimum value.
        max(float): Maximum value.
        retry(int): #Retries before erroring. Zero=infinite.
        timer(int): Time between retries (ms)

    """

    val: float | None = None
    evt: Event | bool = False
    err: float | None = None
    exc: Exception | None = None
    rr: int = 0
    retries: int = 0

    def __init__(
        self,
        cfg: dict,
        rdr: Callable[Awaitable[float], []],
        min: float = -99999,  # noqa:A002
        max: float = 99999,  # noqa:A002
    ) -> float:
        self.cfg = cfg
        self.rdr = rdr
        self.min = min
        self.max = max

    def state(self) -> dict:
        "State monitoring stuff"
        res = dict(r=self.retries, rr=self.rr, val=self.val)
        if self.err is not None:
            res["err"] = self.err
            self.err = None
        return res

    async def get(self):
        "Read the next bit"

        # This dance ensures that an event is only allocated when more than
        # one task tries to read at the same time

        if self.evt is True:
            self.evt = Event()
        if isinstance(self.evt, Event):
            while isinstance(self.evt, Event):
                await self.evt.wait()
            return self.val

        self.evt = True
        self.rr = 0
        rep = self.cfg.get("repeat", 3)
        while True:
            try:
                val = await self.rdr()
            except Exception as exc:
                if self.exc is None:
                    self.exc = exc
            if self.cfg.get("min", self.min) < val < self.cfg.get("max", self.max):
                break
            self.err = val
            if rep:
                rep -= 1
                if rep == 0:
                    exc, self.exc = self.exc, None
                    raise exc
            self.rr += 1
            self.retries += 1
            await sleep_ms(self.cfg.get("timer", 20))
        self.retries -= 1
        self.exc = None

        if isinstance(self.evt, Event):
            self.evt.set()
        self.val = val
        return val


class Sensor(BaseCmd):
    """
    This is the base class for a simple (one-value) sensor.

    Parameters:
        min(float): Minimum value.
        max(float): Maximum value.
        retry(int): #Retries before erroring. Zero=infinite.
        timer(int): Time between retries (ms)

    You might want to override:
    - MIN: default minimum value
    - MAX: default maximum value
    """

    _wants: Event
    _gets: Event
    val: float
    retries: int = 0

    MIN: ClassVar[int | float] = -999999
    MAX: ClassVar[int | float] = 999999

    async def setup(self):
        "Allocate events"
        await super().setup()
        self._rep = Repeater(self.cfg, self.read, min=self.MIN, max=self.MAX)

        self._wants = Event()
        self._gets = Event()

    doc = dict(
        _c=dict(
            _d="Sensor base",
            min="float:min value",
            max="float:max value",
            retry="int:before error; zero=inf",
            timer="int:error delay(ms)",
        ),
        _d="read",
        t="int:ms between reads when streaming, default 10s",
        o="bool:old: wait until value differs",
    )

    async def read(self):
        """
        Read a value. Must be overridden.
        """
        raise NotImplementedError

    doc_st = dict(
        _d="Status", _r=dict(val="float:last value", r="int:Retries", rr="int:current retries")
    )

    async def cmd_st(self):
        "Status"
        return self._rep.state()

    async def stream(self, msg: Msg):
        "Wait for change if @o (old value) is not None"
        t = msg.get("t", 10000)
        o = msg.get("o", None)
        d = msg.get("d", 0)
        if msg.can_stream:
            async with msg.stream_out() as m:
                while True:
                    val = self._rep.get()
                    if o is None or abs(val - o) > d:
                        await m.send(val)
                        if o is not None:
                            o = val
                    await sleep_ms(t)

        val = await self._rep.get()
        while o is not None and abs(val - o) <= d:
            await sleep_ms(t)
            val = await self._get()
        await msg.result(val)
