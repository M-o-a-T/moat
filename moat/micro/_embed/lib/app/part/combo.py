# special combo parts

from moat.compat import TaskGroup
from moat.util import attrdict
from moat.micro._common import _Remote

class Server(_Remote):
    """
    A generic reader that fetches a value from the server
    """
    pass


class Array:
    """
    A generic reader that builds a list of values
    """
    def __init__(self, cmd, cfg, **kw):
        self.parts = []

        std = cfg.get("default",{})
        for p in cfg.parts:
            if not isinstance(p,dict):
                p = attrdict(pin=p)
            for k,v in std.items():
                p.setdefault(k,v)

            self.parts.append(load_from_cfg(p, cmd, **kw))


    async def run(self):
        "Start the parts' background tasks"
        async with TaskGroup() as tg:
            for p in self.parts:
                await tg.spawn(p.run)


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


class RelADC: 
    """
    A generic ADC that returns a relative value.

    Specialized versions might use a delta instead.
    """
    def __init__(self, cmd, cfg, **kw):
        pin = cfg.pin
        ref = cfg.ref
        if not isinstance(ref,dict):
            ref = attrdict(pin=ref)

        for k,v in pin.items():
            ref.setdefault(k,v)

        self.pos = load_from_cfg(pin, cmd, **kw)
        self.neg = load_from_cfg(ref, cmd, **kw)
    
    async def run(self):
        async with TaskGroup() as tg:
            await tg.spawn(self.pos.run)
            await tg.spawn(self.neg.run)

    async def read(self):
        p = n = None
        async def get_rel():
            nonlocal n
            n = await self.neg.read()
        self._tg.start_soon(get_rel)
        p = await self.pos.read()

        return p - n

