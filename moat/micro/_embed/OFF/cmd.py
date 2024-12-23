from __future__ import annotations

from moat.util import NotGiven

from moat.micro.cmd import BaseCmd


class BMSCmd(BaseCmd):
    def __init__(self, parent, name, cfg):
        super().__init__(parent, name)
        self.cfg = cfg

    async def run(self):
        try:
            await self.batt.run(self)
        finally:
            self.batt = None

    async def config_updated(self, cfg):
        await super().config_updated(cfg)
        await self.batt.config_updated(cfg)

    async def cmd_rly(self, st=NotGiven):
        """
        Called manually, but also irreversibly when there's a "hard" cell over/undervoltage
        """
        if self.batt.relay is None:
            raise RuntimeError("No Relay")
        if st is NotGiven:
            return self.batt.relay.value(), self.batt.relay_force
        await self.batt.set_relay_force(st)

    loc_rly = cmd_rly

    async def cmd_info(self, gen=-1, r=False):
        if self.bms.gen == gen:
            await self.bms.xmit_evt.wait()
        return self.bms.stat(r)

    loc_info = cmd_info

    def cmd_live(self):
        self.bms.set_live()

    loc_live = cmd_live
