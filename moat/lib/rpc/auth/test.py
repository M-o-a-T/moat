"""
Test auth.
"""

from __future__ import annotations

from moat.lib.micro import L

from ._base import SubAuth as _SubAuth

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.lib.rpc import MsgSender


class SubAuth(_SubAuth):
    """
    Auth method for testing.

    It requires an 'ok' parameter that gets forwarded to the remote side.

    True/False/None means Accept/Deny/Ignore. Ignore is the default.
    """

    def __init__(
        self, cfg: dict, auth: dict | None, parent, idx: int, name: str, remote: MsgSender
    ):
        super().__init__(cfg)
        self.idx = idx
        self.name = name
        self.parent = parent
        self.remote = remote
        self.auth = auth or {}
        self.is_server = parent.parent.is_server

    async def task(self):
        """Handle this auth method."""
        if L:
            self.set_ready()

        if self.is_server:
            return
        if res := await self.remote.test(self.auth.get("ok")):
            self.accept()
        elif res is False:
            self.deny()
        # otherwise do nothing

        return

    async def cmd_test(self):
        """Handle receiving a request for this auth method"""
        return self.auth.get("ok")
