"""
Watchdog timer.

This app works with a hardware watchdog. It falls back to software if necessary.

There is one main "wdt" option which 

* hw

  Use/control the hardware watchdog. If set, ot

* timeout

  Main control. Cannot be turned off.

* external

  Require external keepalives. Reboot if they're missing.
"""
import sys

import machine
from moat.micro.cmd import BaseCmd
from moat.micro.compat import Event, TimeoutError, wait_for_ms
from moat.micro.wdt import WDT, M


class WDTCmd(BaseCmd):
    """
    Watchdog Timer control.
    """
    wdt = None
    timeout = None

    def __init__(self, parent, name, cfg, gcfg):
        super().__init__(parent)
        self.cfg = cfg
        self._ping = Event()
        if cfg.get("hw", False) and M.WDT is not None:
            self.wdt = M.WDT
        else:
            self.wdt = WDT(cfg)

    async def run(self):
        await self.wdt.run()

    async def config_updated(self, cfg):
        await super().config_updated(cfg)
        self.wdt._setup(cfg)
        self.wdt.ping()

    def cmd_x(self, f=False):
        """
        External keepalive.

        @f: "force" param of `WDT.ping`.
        """
        self.wdt.ping(force=f)

    def cmd_info(self):
        if self.wdt is None:
            return None
        return dict(t=self.wdt.timeout, x=self.wdt.cfg["ext"], h=(self.wdt.wdt is not None))

