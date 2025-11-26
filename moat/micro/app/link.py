"""
Apps used for interconnecting.
"""

from __future__ import annotations

import moat
from moat.util import ensure_cfg
from moat.link.announce import announcing
from moat.link.client import Link
from moat.micro.cmd.base import BaseCmd, MsgSender
from moat.util.compat import AC_use
from moat.util.exc import ExpKeyError

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.micro.cmd.msg import Msg


class Register(BaseCmd):
    """
    This command registers a link between a MoaT-micro path and a MoaT-Link subcommand.

    Config:
       link: !P foo.bar  # for registration of foo.bar on MoaT-Link
       host: bool        # whether to host-prefix the link name, default False
       path: !P r.x      # path to the advertised MoaT-micro (sub)system (if any)
       rlink: !P foo.baz # forward local commands to this

    `link` is mandatory, should be unique, and registers this subcommand in MoaT-Link.
    If `path` is set, accessing @link via :meth:`moat.link.client.LinkSender.get_service`
    connects to it.

    If `rlink` is set, MoaT-micro commands are forwarded to this MoaT-Link
    service.
    """

    rlink: MsgSender | None = None

    async def setup(self):
        "set up the link"
        await super().setup()
        cfg = ensure_cfg("moat.link", moat.cfg)
        self.link = await AC_use(self, Link(cfg.link, common=True))
        if "path" in self.cfg:
            self.ann = await AC_use(
                self,
                announcing(
                    self.link,
                    self.cfg.link,
                    host=self.cfg.get("host", False),
                    service=self.root.sub_at(self.cfg.path),
                ),
            )
        # rlink will be set up lazily

    async def task(self):
        "just start announcing"
        self.ann.set()
        await super().task()

    async def handle(self, msg: Msg, rcmd: list, *prefix: list[str]):
        "forward, possibly"
        if self.rlink is None:
            if "rlink" not in self.cfg:
                raise ExpKeyError(rcmd)
            self.rlink = await self.link.get_service(self.cfg["rlink"])

        try:
            return await self.rlink.handle(msg, rcmd, *prefix)
        except BaseException:
            self.rlink = None
            raise
