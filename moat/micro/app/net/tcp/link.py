"""
TCP link app for MoaT message exchange.
"""

from __future__ import annotations

from moat.util import attrdict
from moat.lib.stream import TcpLink
from moat.micro.cmd.stream.cmdmsg import CmdMsg
from moat.micro.stacks.console import console_stack


class Link(CmdMsg):
    """
    An app that connects to a remote socket.
    """

    def __init__(self, cfg):
        stack = console_stack(
            TcpLink(
                cfg.get("host", "127.0.0.1"),
                cfg["port"],
                retry=cfg.get("retry", attrdict()),
            ),
            cfg,
        )
        super().__init__(stack, cfg)
