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

from __future__ import annotations

from moat.micro.cmd.base import BaseCmd
from moat.micro.compat import Event, L
from moat.micro.wdt import WDT, M


class Cmd(BaseCmd):
    """
    Watchdog Timer control.
    """

    wdt = None
    timeout = None

    def __init__(self, cfg):
        super().__init__(cfg)
        self._ping = Event()
        if cfg.get("hw", False) and M.WDT is not None:
            self.wdt = M.WDT
        else:
            self.wdt = WDT(cfg)

    async def task(self):  # noqa:D102
        self.wdt.setup()
        if L:
            self.set_ready()
        await self.wdt.run()

    async def reload(self):  # noqa:D102
        await super().reload()
        self.wdt.setup()
        self.wdt.ping()

    async def cmd_x(self, f=False, n=None):  # noqa:ARG002
        """
        External keepalive.

        @f: "force" param of `WDT.ping`.
        """
        self.wdt.ping(force=f)

    async def cmd_set(self, t=None):
        """
        Set the watchdog timeout.

        Returns the previosu value.
        """
        return self.wdt.tmo(t)

    async def cmd_info(self):
        """
        Current watchdog state::

            t: timeout
            x: external cfg
            h: hot?
        """
        if self.wdt is None:
            return None
        return dict(t=self.wdt.timeout, x=self.wdt.cfg["ext"], h=(self.wdt.wdt is not None))
