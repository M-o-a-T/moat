"""
Readers that aggregate multiple results
"""

from moat.micro.compat import TaskGroup
from moat.util import attrdict, load_from_cfg
from moat.micro.link import Reader

class Array(Reader):
    """
    A generic reader that builds a list of values

    Configuration:
    - default: common parameter for all parts
      typically includes "client" or "server" tags
    - parts: array with separate config for paths
      typically includes pin numbers
    """
    def __init__(self, cfg, **kw):
        super().__init__(cfg, **kw)

        self.parts = []

        std = cfg.get("default",{})
        for p in cfg.parts:
            if not isinstance(p,dict):
                p = attrdict(pin=p)
            for k,v in std.items():
                p.setdefault(k,v)

            self.parts.append(load_from_cfg(p, **kw))


    async def run(self, cmd):
        "Start the parts' background tasks"
        async with TaskGroup() as tg:
            for p in self.parts:
                await tg.spawn(p.run, cmd)


    async def read(self):
        """
        Return all values as an array
        """
        res = [None]*len(self.parts)
        async def proc(n):
            r = await self.parts[n]
            res[n] = r
        async with TaskGroup() as tg:
            for i in range(len(self.parts)):
                tg.start_soon(proc, i)
        return res


class Subtract(Reader):
    """
    A generic reader that returns a relative value.
    """
    def __init__(self, cfg, **kw):
        pin = cfg.pin
        ref = cfg.ref
        if not isinstance(ref,dict):
            ref = attrdict(pin=ref)

        for k,v in pin.items():
            ref.setdefault(k,v)

        self.pos = load_from_cfg(pin, **kw)
        self.neg = load_from_cfg(ref, **kw)
    
    async def run(self, cmd):
        async with TaskGroup() as tg:
            await tg.spawn(self.pos.run, cmd)
            await tg.spawn(self.neg.run, cmd)

    async def read_(self):
        p = n = None
        async def get_rel():
            nonlocal n
            n = await self.neg.read()
        self._tg.start_soon(get_rel)
        p = await self.pos.read()

        return p - n


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

    async def read_(self):
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

        return dict(u=now_u, i=now_i, p=now_u*now_i)
