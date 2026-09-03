"helpers"

from __future__ import annotations

from moat.lib.micro import CancelledError, Event, sleep_ms
from moat.lib.rpc import BaseCmd

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.lib.rpc import Msg

    from collections.abc import Awaitable, Callable
    from typing import Any, ClassVar

# like get/set_part but without the attributes

TEST_MAGIC = b"r:\x0dn:\x0arn:\x0d\x0a-\x00x\x0ce\x1b" + "🖖🏼  ".encode("utf-8") + b"!"


def get_p(cur: dict, p: tuple, add: bool = False) -> dict:
    """Retrieve an item."""
    for pp in p:
        try:
            cur = cur[pp]
        except KeyError:
            if not add:
                raise
            cur[pp] = nc = {}
            cur = nc
    return cur


def set_p(cur: dict, p: tuple, v: Any) -> None:
    """Set an item."""
    cur = get_p(cur, p[:-1], add=True)
    cur[p[-1]] = v


def del_p(cur: dict, p: tuple) -> None:
    """Delete an item."""
    pp = p[0]
    if pp in cur:
        if len(p) > 1:
            del_p(cur[pp], p[1:])
        if cur[pp]:
            return
        del cur[pp]


class Repeater:
    """
    Support for repeating a measurement.

    Parameters:
        min(float): Minimum value.
        max(float): Maximum value.
        retry(int): #Retries before erroring. Zero=infinite.
        timer(int): Time between retries (ms)
        diff(float): Maximum difference between old and new values.

    Arguments:
        cfg: Config data.
        rdr: The async procedure to retrieve the value.
        min: default minimum
        max: default maximum
        diff: default max delta
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
        rdr: Callable[[], Awaitable[float]],
        min: float = -99999,  # noqa:A002
        max: float = 99999,  # noqa:A002
        diff: float = 99999,
    ) -> None:
        self.cfg: dict = cfg
        self.rdr: Callable[[], Awaitable[float]] = rdr
        self.min: float = min
        self.max: float = max
        self.diff: float = diff

    def state(self) -> dict:
        """Current state."""
        res = dict(r=self.retries, rr=self.rr, val=self.val)
        if self.err is not None:
            res["err"] = self.err
            self.err = None
        if self.evt:
            res["wait"] = self.evt is not True
        return res

    async def get(self, force: bool = False) -> float:
        """
        Read the next bit. Ignore the *diff* parameter if *force* is
        ``True``.
        """

        # This dance ensures that an event is only allocated when more than
        # one task tries to read at the same time

        if force:
            return await self.rdr()

        if self.evt is True:
            self.evt = Event()
        if isinstance(self.evt, Event):
            while isinstance(self.evt, Event):
                await self.evt.wait()
            return self.val  # type:ignore[return-value]

        try:
            self.evt = True
            self.rr = 0
            rep: int | None = self.cfg.get("repeat", 3)
            val: float | None = None
            err: Exception | None = None
            while True:
                try:
                    val = await self.rdr()
                except Exception as exc:
                    if err is None:
                        err = exc
                if val is not None and self.cfg.get("min", self.min) < val < self.cfg.get(
                    "max",
                    self.max,
                ):
                    if self.val is None or abs(val - self.val) < self.cfg.get("diff", self.diff):
                        break
                self.err = val
                if rep:
                    rep -= 1
                    if rep == 0:
                        raise err or ValueError(val)
                self.rr += 1
                self.retries += 1
                await sleep_ms(self.cfg.get("timer", 20))
            if self.retries > 0:
                self.retries -= 1
        except BaseException:
            val = None
            raise
        finally:
            if isinstance(self.evt, Event):
                self.evt.set()
            self.evt = False
        if val is None:
            raise err or CancelledError
        self.val = val
        return val


class Sensor(BaseCmd):
    """
    This is the base class for a simple (one-value) sensor.

    The parameters from `Repeater` are used.

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

    async def setup(self) -> None:
        """Allocate events."""
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

    async def read(self) -> float:
        """
        Read a value. Must be overridden.
        """
        raise NotImplementedError

    doc_st = dict(
        _d="Status", _r=dict(val="float:last value", r="int:Retries", rr="int:current retries")
    )

    async def cmd_st(self) -> dict:
        """Status."""
        return self._rep.state()

    async def stream(self, msg: Msg) -> None:
        """Wait for change if @o (old value) is not None."""
        t: int = msg.get("t", 10000)
        o: float | None = msg.get("o", None)
        d: float = msg.get("d", 0)
        if msg.can_stream:
            async with msg.stream_out() as m:
                while True:
                    val = await self._rep.get()
                    if o is None or abs(val - o) > d:
                        await m.send(val)
                        if o is not None:
                            o = val
                    await sleep_ms(t)

        val = await self._rep.get(msg.get("force", False))
        while o is not None and abs(val - o) <= d:
            await sleep_ms(t)
            val = await self._rep.get(msg.get("force", False))
        await msg.result(val)
