from __future__ import annotations

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

    doc_rly = dict(
        _d="relay get/force-set", st="bool?:forced state", _r=["bool:state", "bool:forced?"]
    )

    async def cmd_rly(self, msg):
        """
        Force the relay (st=bool), un-force it (st=None), or return the
        current state (st missing).

        Called manually, but also irreversibly when there's a "hard" cell over/undervoltage
        """
        if self.batt.relay is None:
            raise RuntimeError("No Relay")
        if "st" in msg:
            await self.batt.set_relay_force(msg["st"])
        else:
            return self.batt.relay.value(), self.batt.relay_force

    loc_rly = cmd_rly

    doc_info = dict(_d="incr status", gen="int:old state", r="bool:reset", _r="dict")

    async def cmd_info(self, msg):
        if self.bms.gen == msg.get("gen", -1):
            await self.bms.xmit_evt.wait()
        return self.bms.stat(msg.get("r", False))

    loc_info = cmd_info

    def cmd_live(self):
        self.bms.set_live()

    loc_live = cmd_live
