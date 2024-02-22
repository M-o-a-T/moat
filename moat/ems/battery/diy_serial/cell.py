from .._base import BaseCell
from ..conv.steinhart import thermistor2celsius,celsius2thermistor
from .packet import RequestVoltages,RequestReadSettings,RequestTemperature

class Cell(BaseCell):
    """
    Direct (inefficient!) interface to a single serially-connected cell.

    @comm: BattComm instance
    @i: cell number there

    This BaseCell translates commands to Comm requests.
    """
    code_version = None
    board_version = None
    v_per_ADC = None
    v_calibration = None
    load_maxtemp_raw = None
    balance_config_threshold_raw = None
    internal_B = None
    external_B = None
    n_samples = None
    load_resistance_raw = None

    def __init__(self, cfg):
        super().__init__(cfg)

    async def setup(self):
        await super().setup()
        self.comm = self.root.sub_at(*self.cfg["comm"])
        res = (await self.comm(p=RequestReadSettings(), s=self.cfg.pos))[0]
        res.to_cell(self)

    async def cmd_u(self):
        "read cell voltage"
        res = (await self.comm(p=RequestVoltages(), s=self.cfg.pos))[0]
        return res.voltRaw * self.v_per_ADC / self.n_samples * self.v_calibration  # + self.cfg.u.offset

    async def cmd_t(self):
        "read cell temperature"
        res = (await self.comm(p=RequestTemperature(), s=self.cfg.pos))[0]
        if res.extRaw == 0:
            return None
        return thermistor2celsius(self.external_B, res.extRaw)

    async def cmd_tb(self):
        "read balancer temperature"
        res = (await self.comm(p=RequestTemperature(), s=self.cfg.pos))[0]
        if res.intRaw == 0:
            return None
        return thermistor2celsius(self.internal_B, res.intRaw)

