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

        def __new__(cls, **kw):  # noqa:ARG003
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

    def value(self, n=None):
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
    This is a basic analog pin.

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

    def iter_r(self):
        "iterate the pin's values"
        return self.pin

    doc_r = dict(_d="read", o="bool:old, wait until not this")

    async def cmd_r(self, o=None):
        "Wait for change if @o (old value) is not None"
        if o is not None and self.pin() == o:
            await self.pin.evt.wait()
        return self.pin.val

    doc_w = dict(_d="write", _0="bool:new value")

    async def cmd_w(self, v):
        "Set pin value"
        self.pin.value(v)
