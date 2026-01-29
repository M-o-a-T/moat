"""
Module for pins
"""

from __future__ import annotations

import asyncio

from moat.lib.micro import AC_use, Event, TaskGroup
from moat.lib.rpc import BaseCmd

try:
    import machine as M
except ImportError:
    M = None

try:
    _XPin = M.Pin

except AttributeError:

    class _XPin:
        # fake
        __val = False

        def __new__(cls, **kw):  # noqa: ARG004
            return object.__new__(cls)

        def __init__(self, **kw):
            pass

        def value(self, n=None):
            if n is None:
                return self.__val
            else:
                self.__val = None

        def irq(self, p, flg):
            pass

        IRQ_RISING = 1
        IRQ_FALLING = 2


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
        self._pin = _XPin(*a, **kw)
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
            self._pin.irq(self._irq, _XPin.IRQ_FALLING | _XPin.IRQ_RISING)
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
        )
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

    doc_r = dict(
        _d="read",
        _o=True,
        _s=True,
        _r="bool:current value",
        o="bool:old: wait until pin value differs",
    )

    async def stream_r(self, msg):
        "Wait for change if @o (old value) is not None"
        o = msg.get("o", None)
        if msg.can_stream:
            async with msg.stream_out() as m:
                val = bool(self.pin())
                if o is None or val != o:
                    await m.send(val)
                while True:
                    await self.pin.evt.wait()
                    await m.send(bool(self.pin()))

        val = bool(self.pin())
        if val is o:
            await self.pin.evt.wait()
            val = bool(self.pin())
        await msg.result(val)

    doc_w = dict(
        _d="write",
        _s=True,
        _i=True,
        _0="bool:new value",
    )

    async def stream_w(self, msg):
        "Set pin value"
        if msg.can_stream:
            async with msg.stream_in() as m:
                for mm in m:
                    self.pin(mm[0])
            return

        self.pin(msg[0])
        await msg.result()
