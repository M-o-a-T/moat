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

    def __new__(cls, cmd, cfg, **kw):
        cmd  # unused
        kw["id"] = cfg.pin
        self = super().__new__(**kw)
        self.flag = uasyncio.ThreadSafeFlag()

    def __init__(self, cfg, **kw):
        pass

    def _irq(self):
        self.flag.set()

    async def __aenter__(self):
        self.irq(self._irq, M.Pin.FALLING|M.Pin.RISING)
        self.flag.set()

    async def __aexit__(self, *err):
        self.irq(None)

    def __aiter_(self):
        return self

    async def __anext__(self):
        await self.flag.wait()
        self.flag.clear()
        return self.pin.value()

    async def run(self, cmd):
        async with self:
            while True:
                await uasyncio.sleep(9999)

    async def get(self):
        return super().value()

    async def set(self, value):
        super().value(value)

    async def on(self):
        super().on()

    async def off(self):
        super().off()
