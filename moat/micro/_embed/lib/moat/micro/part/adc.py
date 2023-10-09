"""
Module for pins
"""
import machine as M
from moat.compat import TaskGroup, load_from_cfg, sleep_ms
from moat.util import attrdict

from .link import Reader


class ADC(M.ADC):
    """
    A config-enabled pin that you can async-iterate for changes.

        p = Pin(attrdict(pin=3), mode=machine.Pin.IN)
        with p:
            async for val in p:
                print("Pin",p,"is now",val)

    All other import arguments are taken from keywords.

    This class pseudo-multiple-inherits from Reader.
    """

    def __new__(cls, cfg, **kw):
        kw["id"] = cfg.pin
        self = super().__new__(**kw)
        self.cfg = cfg
        return self

    def __init__(self, cfg, **kw):
        self.n = cfg.get("n", 1)
        self.nn = cfg.get("nn", 1)
        self.dly = cfg.get("delay", 1)
        self.factor = cfg.get("factor", 1) / self.n / self.nn
        self.offset = cfg.get("offset", 0)
        Reader.__init__(self, cfg)

    async def run(self, cmd):
        await Reader.run(cmd)

    async def read(self):
        c = 0
        for a in range(self.nn):
            if a:
                await sleep_ms(self.dly)
            for b in range(self.n):
                c += self.read_u16()
        res = c * self.factor + self.offset
        await self.send(res)
        return res

    async def send(self, **msg):
        await Reader.send(**msg)


class Multiply(Reader):
    """
    Measure/aggregate data by multiplying two readouts.

    Useful e.g. for power (separate channels for U and I).

    Returns a dict with u,i,p.
    """

    def __init__(self, cfg, **kw):
        super().__init__(cfg, **kw)
        self.rdr_u = load_from_cfg(cfg.u)
        self.rdr_i = load_from_cfg(cfg.u)

    async def read(self):
        now_u = None
        now_i = None

        async with TaskGroup() as tg:

            async def rd_u():
                nonlocal now_u
                now_u = await self.rdr_u.read()

            async def rd_i():
                nonlocal now_i
                now_i = await self.rdr_i.read()

            tg.start_soon(rd_u)
            tg.start_soon(rd_i)

        res = dict(u=now_u, i=now_i, p=now_u * now_i)
        await self.send(res)
        return res
