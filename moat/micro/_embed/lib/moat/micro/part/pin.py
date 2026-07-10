"""
Module for pins
"""

from __future__ import annotations

import asyncio
import machine as M

from moat.util import NotGiven
from moat.lib.micro import AC_use, Event, TaskGroup
from moat.lib.rpc import BaseCmd


class _Pin:
    """
    A config-enabled pin that you can async-iterate for changes.

        p = Pin(attrdict(pin=3), mode=machine.Pin.IN)
        with p:
            async for val in p:
                print("Pin",p,"is now",val)

    All other import arguments are taken from keywords.
    """

    def __init__(self, *a, **kw):
        self._pin = M.Pin(*a, **kw)
        self.flag = asyncio.ThreadSafeFlag()
        self.evt = Event()
        self.val = self._pin.value()

    def _irq(self, _x=None):
        "sets the change flag"
        self.val = self._pin.value()
        self.flag.set()

    def __call__(self, n=None):
        if n is None:
            return self._pin.value()
        else:
            self._pin.value(n)
            self.val = self._pin.value()
            self.flag.set()

    async def flag_watch(self):
        "Flag reader task, since a ThreadSafeFlag only acepts one read task"
        try:
            self._pin.irq(self._irq, M.Pin.IRQ_FALLING | M.Pin.IRQ_RISING)
            while True:
                await self.flag.wait()
                self.flag.clear()
                self.evt.set()
                self.evt = Event()
        finally:
            self._pin.irq(None)

    async def __aenter__(self):
        self.flag.set()

    async def __aexit__(self, *err):
        pass

    def __aiter__(self):
        return self

    async def __anext__(self):
        await self.evt.wait()
        return self.pin()


class Pin(BaseCmd):
    """
    This is a basic digital pin.

    Iterating it yields a new value whenever the pin changes.

    Parameters:
        out(bool): direction (input: `False`)
        drive(int): drive strength. ``0…3`` on ESP32.
        init(bool): initial value. Leave alone if not given.
        pull(bool|None): Pull-up (`True`), -down (`False`).
        open(bool|None): open-collector/drain (`True`) or
                         -emitter/source (`False`), on output.
    """

    doc = dict(
        _c=dict(
            _d="Digital I/O pin",
            pin="int:Nr",
            out="bool:output?",
            init="bool:initial out state",
            drive="int:strength",
            pull="bool|None: Pullup/down?",
            open="bool|None: open-collector/emitter?",
        ),
        _d="r/w",
        _a=[
            dict(_r="bool:current state"),
            dict(
                _0="bool:new state",
                o="bool:old: wait until pin value differs",
            ),
        ],
        _o=True,
        _s=True,
    )

    def __init__(self, cfg):
        super().__init__(cfg)
        out = cfg.get("out", False)
        oce = cfg.get("open", None)  # open collector/emitter

        a = [cfg["pin"], (M.Pin.OPEN_DRAIN if oce else M.Pin.OUT) if out else M.Pin.IN]
        kw = {}
        if (val := cfg.get("init", None)) is not None:
            kw["value"] = val
        if (drive := cfg.get("drive", None)) is not None:
            kw["drive"] = getattr(M.Pin, f"DRIVE_{drive}", 0)
        if (pull := cfg.get("pull", None)) is not None:
            a.append(M.Pin.PULL_UP if pull else M.Pin.PULL_DOWN)

        self.pin = _Pin(*a, **kw)

    async def setup(self):
        "initialization, triggers change"
        await super().setup()
        if getattr(self, "tg", None) is None:
            self.tg = await AC_use(self, TaskGroup())
        await self.tg.spawn(self.pin.flag_watch)

    async def cmd(self, val: bool = NotGiven) -> None | bool:
        "Simple Data protocol."
        if val is NotGiven:
            return self.pin()
        self.pin(val)

    async def stream(self, msg):
        """
        R/W data stream. The initial argument says whether you want to
        read. Waits for change if @o (old value) is not None.
        """
        o = msg.get("o", None)
        async with TaskGroup() as tg, msg.stream() as m:

            async def _rd():
                val = bool(self.pin())
                if o is not val:
                    await m.send(val)
                while True:
                    await self.pin.evt.wait()
                    await m.send(bool(self.pin()))

            if o is not None or msg.get(0, False):
                tg.start_soon(_rd)

            for mm in m:
                self.pin(mm[0])
            tg.cancel()
            await msg.result()
