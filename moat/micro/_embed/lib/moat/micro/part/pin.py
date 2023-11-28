"""
Module for pins
"""
from __future__ import annotations

import asyncio

import machine as M

from moat.micro.cmd.base import BaseCmd
from moat.micro.compat import AC_use, Event, TaskGroup

try:
    sup = M.Pin
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

    sup = _XPin


class _Pin(sup):
    """
    A config-enabled pin that you can async-iterate for changes.

        p = Pin(attrdict(pin=3), mode=machine.Pin.IN)
        with p:
            async for val in p:
                print("Pin",p,"is now",val)

    All other import arguments are taken from keywords.
    """

    def __new__(cls, pin, **kw):
        kw["id"] = pin
        self = super().__new__(cls, **kw)
        self.flag = asyncio.ThreadSafeFlag()
        self.evt = Event()
        self.val = False
        return self

    def __init__(self, **kw):
        super().__init__(**kw)

    def _irq(self):
        "sets the change flag"
        self.val = self.value()
        self.flag.set()

    async def flag_watch(self):
        "Flag reader, since a ThreadSafeFlag only acepts one task"
        while True:
            if self.value() == self.val:
                await self.flag.wait()
                self.flag.clear()
            self.evt.set()
            self.evt = Event()

    async def __aenter__(self):
        self.irq(self._irq, M.Pin.FALLING | M.Pin.RISING)
        self.flag.set()

    async def __aexit__(self, *err):
        self.irq(None)

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
        self.flag.set()
        self.flag = Event()

    def iter_r(self):
        "iterate the pin's values"
        return self.pin

    async def cmd_r(self, o=None):
        "read. Wait for change if @o (old value) is not None"
        if o is None or self.pin() is o:
            await self.pin.evt.wait()
        return self._value

    async def cmd_w(self, v):
        "write. Set pin value"
        self.pin(v)
        self.pin.evt.set()
