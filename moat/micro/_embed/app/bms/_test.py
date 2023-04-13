from moat.micro.compat import TaskGroup
from moat.micro.part.combo import Array
from moat.micro.link import Reader
try:
    # server
    from moat.micro.app.bms._base import BaseBattery, BaseCells
except ImportError:
    from app.bms._base import BaseBattery, BaseCells

class CellArray(Array):
    PARTS = "cells"
    ATTR = None

class Cells(BaseCells):
    def __init__(self, cfg, bms=None, **kw):
        super().__init__(cfg, **kw)
        self.n_cells = cfg.n
        self.cells = CellArray(cfg)
        self.bms = bms

        Reader.__init__(self, cfg)
    
    async def run(self, cmd):
        await self.cells.run(cmd)

    async def read_u(self):
        res = []
        for c in self.cells:
            res.append(await c.read_u())
        #res = [await c.read_u() for c in self.cells]
        await Reader.send(self, dict(u=res))
        return res

    async def read_t(self):
        res = []
        for c in self.cells:
            res.append(await c.read_t())
        #res = [await c.read_t() for c in self.cells]
        await Reader.send(self, dict(t=res))
        return res

class Cell:
    def __init__(self, cfg):
        self.u = cfg.u
        self.t = cfg.t

    async def read_u(self):
        return self.u

    async def read_t(self):
        return self.t

    async def run(self, cmd):
        pass

class Static(Reader):
    def __init__(self, cfg, **kw):
        self.val = cfg.value

    async def read_(self):
        return self.val


class Batt(BaseBattery):
    pass
        
