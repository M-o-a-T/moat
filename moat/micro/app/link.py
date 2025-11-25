"""
Apps used for interconnecting.
"""

from __future__ import annotations

import moat
from moat.util import ensure_cfg
from moat.link.announce import announcing
from moat.link.client import Link
from moat.micro.cmd.base import BaseCmd
from moat.util.compat import AC_use


class Register(BaseCmd):
    """
    This command registers a link to a remote device.

    Config:
       link: !P foo.bar  # for registration of foo.bar on MoaT-Link
       host: bool        # whether to host-prefix the link name, default False
       path: !P r.x      # path to the advertised remote (sub)system

    """

    async def setup(self):
        "set up the link"
        await super().setup()
        cfg = ensure_cfg("moat.link", moat.cfg)
        self.link = await AC_use(self, Link(cfg.link, common=True))
        self.ann = await AC_use(
            self,
            announcing(
                self.link,
                self.cfg.link,
                host=self.cfg.get("host", False),
                service=self.root.sub_at(self.cfg.path),
            ),
        )

    async def task(self):
        "just start announcing"
        self.ann.set()
        await super().task()
