"""
Apps used for interconnecting.
"""

from __future__ import annotations

from moat.link.announce import announcing
from moat.link.client import Link
from moat.micro.cmd.base import BaseCmd
from moat.util.compat import AC_use
from moat.util.config import CFG
from moat.util.exc import ExpKeyError

from ._link import Alert as Alert

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.lib.cmd.base import MsgSender
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

    If `rlink` is set, MoaT-micro commands that are directed to this app
    instance get forwarded to the given MoaT-Link command on the server.
    (Typically you'd use this to connect another MoaT-micro gateway.)
    """

    link: Link | None = None
    rlink: MsgSender | None = None

    async def setup(self):
        "set up the link"
        await super().setup()
        self.link = await AC_use(self, Link(CFG.moat.link, common=True))
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
        if self.link is None:
            raise RuntimeError("Not ready")  # XXX maybe just return
        if self.rlink is None:
            try:
                rpath = self.cfg["rlink"]
            except KeyError:
                raise ExpKeyError(rcmd) from None
            if len(rpath):
                self.rlink = await self.link.get_service(rpath)
            else:
                # empty rpath: direct link access
                self.rlink = self.link

        try:
            return await self.rlink.handle(msg, rcmd, *prefix)
        except BaseException:
            self.rlink = None
            raise
