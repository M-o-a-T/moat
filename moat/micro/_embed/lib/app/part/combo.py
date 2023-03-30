# special combo parts

import uasyncio

from moat.compat import TaskGroup
from moat.util import attrdict

class RelADC: 
    """
    A generic ADC that returns one value relative to another.
    """
    def __init__(self, cfg, **kw):
        pin = cfg.pin
        ref = cfg.ref
        if not isinstance(pin,dict):
            pin = attrdict(pin=pin)
        if not isinstance(ref,dict):
            ref = attrdict(pin=ref)
        for k,v in cfg.items():
            if k in (pin,ref):
                continue
            pin.setdefault(k,v)
            ref.setdefault(k,v)
        pin.setdefault("scale",1)
        ref.setdefault("scale",1)
        pin.setdefault("offset",0)
        ref.setdefault("offset",0)

        self.pos = load_from_cfg(pin, **kw)
        self.neg = load_from_cfg(ref, **kw)
    
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

