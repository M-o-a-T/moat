"""
Websocket link app for MoaT message exchange.
"""

from __future__ import annotations

from moat.util import attrdict
from moat.lib.rpc import CmdMsg
from moat.lib.stream import WsLink, ws_stack


class Link(CmdMsg):
    """
    An app that connects to a remote websocket.
    """

    def __init__(self, cfg):
        path = cfg.get("path", "/")
        if not path.startswith("/"):
            path = "/" + path
        url = cfg.get(
            "url",
            "{}://{}:{}{}".format(
                "wss" if cfg.get("ssl", False) else "ws",
                cfg.get("host", "127.0.0.1"),
                cfg["port"],
                path,
            ),
        )
        stack = ws_stack(
            WsLink(
                url,
                retry=cfg.get("retry", attrdict()),
                subprotocols=cfg.get("subprotocols", None),
            ),
            cfg,
        )
        super().__init__(cfg, stack)
