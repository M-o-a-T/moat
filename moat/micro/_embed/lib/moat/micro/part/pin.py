"""
Module for pins
"""

from __future__ import annotations

import asyncio

from moat.micro.cmd.base import BaseCmd
from moat.util.compat import AC_use, Event, TaskGroup

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

    def _irq(self):
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
        "Flag reader, since a ThreadSafeFlag only acepts one task"
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
    """

    def __init__(self, cfg):
        super().__init__(cfg)
        kw = {}
        if (val := cfg.get("init", None)) is not None:
            kw["value"] = val

        self.pin = _Pin(cfg["pin"], **kw)

    async def setup(self):
        "initialization, triggers change"
        await super().setup()
        if getattr(self, "tg", None) is None:
            self.tg = await AC_use(self, TaskGroup())
        await self.tg.spawn(self.pin.flag_watch)

    doc_r = dict(
        _d="read",
        _s=[
            dict(_o="bool:new values"),
            dict(_r="bool:current value"),
        ],
        o="bool:old: wait until pin value differs",
    )

    async def stream_r(self, msg):
        "Wait for change if @o (old value) is not None"
        o = msg.get("o", None)
        if msg.can_stream:
            async with msg.stream_out() as m:
                val = self.pin()
                if o is None or val != o:
                    await m.send(val)
                while True:
                    await self.pin.evt.wait()
                    await m.send(self.pin())

        val = self.pin()
        if val is o:
            await self.pin.evt.wait()
            val = self.pin()
        return val

    doc_w = dict(
        _d="write",
        _s=[
            dict(_i="bool:new values"),
            dict(_0="bool:new value"),
        ],
    )

    async def stream_w(self, msg):
        "Set pin value"
        if msg.can_stream:
            async with msg.stream_in() as m:
                for mm in m:
                    self.pin(mm[0])
            return

        self.pin(msg[0])
