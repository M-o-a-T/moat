"""
Module for pins
"""
import machine as M

from moat.compat import sleep_ms

class ADC(M.ADC):
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

    def __init__(self, cfg, **kw):
        self.n = cfg.get("n",1)
        self.nn = cfg.get("nn",1)
        self.dly = cfg.get("delay",1)
        self.factor = cfg.get("factor", 1) / self.n / self.nn
        self.offset = cfg.get("offset", 0)

    async def read(self):
        c = 0
        for a in range(self.nn):
            if a:
                await sleep_ms(self.dly)
            for b in range(self.n):
                c += self.read_u16()
        return c * self.factor + self.offset

    async def run(self, cmd):
        pass
