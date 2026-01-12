"""
Apps used for interconnecting.
"""

from __future__ import annotations

from moat.lib.config import CFG
from moat.lib.micro import AC_use
from moat.lib.rpc import BaseCmd
from moat.link.announce import announcing
from moat.link.client import Link
from moat.util.exc import ExpKeyError

from ._link import Alert as Alert

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.lib.path import PathElem
    from moat.lib.rpc import MsgSender
    from moat.lib.rpc.msg import Msg


class Register(BaseCmd):
    """
    This command registers a link between a MoaT-micro path and a MoaT-Link subcommand.

    Parameters:
       link (Path): for registration under this path on MoaT-Link
       host (bool): whether to host-prefix the link name, defaults to `False`
       path (Path): if set, forward remote commands to this local path
       rlink (Path): if set, forward local commands to this server-side path

    `link` is mandatory, should be unique, and registers this subcommand in MoaT-Link.
    If ``path`` is set, accessing @link via :meth:`moat.link.client.LinkSender.get_service`
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
                    service=self.root.sub_at(self.cfg.path) if "path" in self.cfg else None,
                ),
            )
        # rlink will be set up lazily

    async def task(self):
        "just start announcing"
        self.ann.set()
        await super().task()

    async def handle(self, msg: Msg, rcmd: list[PathElem], *prefix: list[str]):
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
