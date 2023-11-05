from moat.util.compat import TaskGroup
from moat.util import pos2val,val2pos
from moat.micro.cmd.array import ArrayCmd

from moat.ems.battery._base import BaseCell, BaseBattery


class Cell(BaseCell):
    """
    Mock battery cell.

    Its nominal charge is 0…1, capacity in amp-sec.

    The voltages are linear between u.ext, plus a power term when exceeding
    that.

    Config::

        c: 0.5
        cap: 2000
        lim:
          t:
            abs:
              min: 0
              max: 45
            ext:
              min: 10
              max: 40
          c:
            min: 0.2
            max: 0.9
          p:  # exponent when 'ext' limit is exceeded
            min: 2
            max: 3
          u:
            abs:
              min: 2.5
              max: 3.65
            ext:
              min: 2.9
              max: 3.4
    """
    def __init__(self, cfg):
        super().__init__(cfg)
        self._c = cfg["c"]
        self._t = cfg["t"]
        self._tb = 25
    
    async def cmd_c(self, c:float|None=None) -> float|None:
        if c is None:
            return self._c
        self._c = c
        return None

    async def cmd_u(self, c:float|None=None):
        li = self.cfg["lim"]
        liu = li["u"]
        if c is None:
            c = self._c
        up = val2pos(li["c"]["min"],c,li["c"]["max"])
        if up < 0:
            fx = val2pos(li["c"]["min"],c,0) ** li["p"]["min"]
            u = pos2val(liu["ext"]["min"],fx,liu["abs"]["min"])
        elif up > 1:
            fx = val2pos(li["c"]["max"],c,1) ** li["p"]["max"]
            u = pos2val(liu["ext"]["max"],fx,liu["abs"]["max"])
        else:
            u = pos2val(liu["ext"]["min"],up,liu["ext"]["max"])
        return u

    async def cmd_t(self):
        return self._t

    async def cmd_tb(self):
        return self._tb

    async def cmd_add_p(self, p, t):
        "add power to the battery: @p watts for @t msec"
        # watt seconds
        self._c += p*t/self.cfg["cap"]/1000

        # incoming power adds heat to the battery
        self._t += (25-self._t)*0.01 + abs(p)*t/100000


class Batt(BaseBattery):
    pass
