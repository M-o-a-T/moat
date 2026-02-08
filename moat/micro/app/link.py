"""
Apps used for interconnecting.
"""

from __future__ import annotations

from moat.lib.config import CFG
from moat.lib.micro import AC_use, L
from moat.lib.path import Path
from moat.lib.rpc import BaseCmd, NotReadyError
from moat.link.announce import announcing
from moat.link.client import Link
from moat.util.exc import ExpKeyError

from ._link import Alert as Alert

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.lib.path import PathElem
    from moat.lib.rpc import MsgSender
    from moat.lib.rpc.msg import Msg
    from moat.link.announce import FakeReady


class Cmd(BaseCmd):
    """
    This command registers a link between a MoaT-micro path and a MoaT-Link subcommand.

    Parameters:
       link (Path): register at this path on MoaT-Link
       host (bool): whether to host-prefix the link name, defaults to `False`
       service (str): additional element(s) for *link*, if set
       target.recv (Path): if set, forward remote commands to this local path
       target.send (Path): if set, forward local commands to this server-side path
       via (Path): announcement to send *rlink* commands to
       mon (bool): allow "mon_" access to monitor data from MoaT-Link.
                   This feature ignores the *via* and *rlink* parameters.

    *link* registers this subcommand in MoaT-Link. If *path* is set,
    accessing @link via :meth:`moat.link.client.LinkSender.get_service`
    connects to it.

    If *target.send* is set, commands to this app get forwarded to the given
    MoaT-Link command on the server. If *via* is set, the result of looking
    up the announcement is prepended.

    The *service* parameter exists so config files can hardcode the link
    but use a relative path to add e.g. the hostname.
    """

    doc = dict(
        _c=dict(
            _d="Remote link",
            link="path:registration",
            host="bool:add hostname to link",
            service="path|str: append to name",
            dest=dict(
                send="path:target for outgoing messages",
                recv="path:target for incoming messages",
            ),
        )
    )

    link: Link | None = None
    rlink: MsgSender | None = None
    ann: FakeReady | None = None

    async def setup(self):
        "set up the link"
        await super().setup()
        self.link = await AC_use(self, Link(CFG.moat.link, common=True))
        srv = self.cfg.get("link")
        if srv is not None:
            if (service := self.cfg.get("service", None)) is not None:
                if isinstance(service, (Path, list, tuple)):
                    srv += service
                else:
                    srv /= service
            target = self.cfg.get("target", {}).get("recv", None)
            self.ann = await AC_use(
                self,
                announcing(
                    self.link,
                    srv,
                    host=self.cfg.get("host", False),
                    service=self.root.sub_at(target) if target is not None else None,
                ),
            )
        # rlink will be set up lazily

    async def task(self):
        "just start announcing"
        if self.ann is not None:
            self.ann.set()
        await super().task()

    async def handle(self, msg: Msg, rcmd: list[PathElem], *prefix: list[str]):
        "forward, possibly"
        if rcmd[0] == "rdy_":
            if L and await self.wait_ready(wait=msg.get("wait", True)):
                raise NotReadyError(msg.cmd, rcmd)

        elif L and await self.wait_ready():
            raise RuntimeError("Not ready")

        if rcmd == ["mon_"] and self.cfg.get("mon", False):
            # read data from there
            return await msg.call_stream(self.link.stream_watch)

        if self.rlink is None:
            try:
                rpath = self.cfg["target"]["send"]
            except KeyError:
                raise ExpKeyError(rcmd) from None
            via = self.cfg.get("via", None)
            link = self.link
            if via is not None:
                link = await link.get_service(via)
            if len(rpath):
                link = link.sub_at(rpath)
            self.rlink = link

        try:
            return await self.rlink.handle(msg, rcmd, *prefix)
        except BaseException:
            self.rlink = None
            raise
