"""
Unix socket link app for MoaT message exchange.
"""

from __future__ import annotations

from moat.util import attrdict
from moat.lib.rpc.stream.cmdmsg import CmdMsg
from moat.lib.stream import UnixLink, serial_stack


class Link(CmdMsg):
    """
    An app that connects to a remote Unix socket.
    """

    def __init__(self, cfg):
        stack = serial_stack(UnixLink(cfg["port"], retry=cfg.get("retry", attrdict())), cfg)
        super().__init__(stack, cfg)
