# special combo parts

import uasyncio

from moat.compat import TaskGroup

class RelADC: 
    """
    A generic ADC that returns one value relative to another.
    """
    def __init__(self, cfg, **kw):
        for k,v in cfg.items():
            if k not in cfg.ref:
                cfg.ref[k] = v

        self.pos = load_from_cfg(cfg, **kw)
        self.neg = load_from_cfg(cfg.ref, **kw)
    
    async def run(self):
        async with TaskGroup() as tg:
            self._tg = tg
            await tg.spawn(self.pos.run)
            await tg.spawn(self.neg.run)
            while True:
                await uasyncio.sleep(9999)

    async def read(self):
        p = n = None
        async def get_rel():
            nonlocal n
            n = await self.neg.read()
        self._tg.start_soon(get_rel)
        p = await self.pos.read()

        return p - n

