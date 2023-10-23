"""
Module for pins
"""
import asyncio

import machine as M
from moat.util import attrdict

from moat.micro.compat import idle

try:
    sup = M.Pin
except AttributeError:

    class XPin:
        __val = False

        def __new__(cls, **kw):
            return object.__new__(cls)

        def __init__(self, **kw):
            pass

        def value(self, n=None):
            if n is None:
                return self.__val
            else:
                self.__val = None

    sup = XPin


class Pin(sup):
    """
    A config-enabled pin that you can async-iterate for changes.

        p = Pin(attrdict(pin=3), mode=machine.Pin.IN)
        with p:
            async for val in p:
                print("Pin",p,"is now",val)

    All other import arguments are taken from keywords.
    """

    def __new__(cls, cfg, **kw):
        kw["id"] = cfg.pin
        self = super().__new__(cls, **kw)
        self.flag = asyncio.ThreadSafeFlag()
        return self

    def __init__(self, cfg, **kw):
        super().__init__(**kw)

    def _irq(self):
        self.flag.set()

    async def __aenter__(self):
        self.irq(self._irq, M.Pin.FALLING | M.Pin.RISING)
        self.flag.set()

    async def __aexit__(self, *err):
        self.irq(None)

    def __aiter__(self):
        return self

    async def __anext__(self):
        await self.flag.wait()
        self.flag.clear()
        return self.pin.value()

    async def run(self, cmd):
        async with self:
            await idle()

    async def get(self):
        return super().value()

    async def set(self, value):
        super().value(value)

    async def on(self):
        super().on()

    async def off(self):
        super().off()
