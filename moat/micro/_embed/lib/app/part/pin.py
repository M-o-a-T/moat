"""
Module for pins
"""
import machine as M
import uasyncio

class Pin(M.Pin):
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
        self = super().__new__(**kw)
        self.flag = uasyncio.ThreadSafeFlag()

    def __init__(self, cfg, **kw):
        pass

    def _irq(self):
        self.flag.set()

    def __enter__(self):
        self.irq(self._irq, M.Pin.FALLING|M.Pin.RISING)
        self.flag.set()

    def __exit__(self, *err):
        self.irq(None)

    def __aiter_(self):
        return self

    async def __anext__(self):
        await self.flag.wait()
        self.flag.clear()
        return self.pin.value()

    async def run(self):
        pass

