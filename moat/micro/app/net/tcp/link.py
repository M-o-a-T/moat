"""
TCP link app for MoaT message exchange.
"""

from __future__ import annotations

from moat.util import attrdict
from moat.lib.rpc import CmdMsg
from moat.lib.stream import TcpLink, serial_stack


class Link(CmdMsg):
    """
    An app that connects to a remote socket.
    """

    def __init__(self, cfg):
        stack = serial_stack(
            TcpLink(
                cfg.get("host", "127.0.0.1"),
                cfg["port"],
                retry=cfg.get("retry", attrdict()),
            ),
            cfg,
        )
        super().__init__(stack, cfg)
