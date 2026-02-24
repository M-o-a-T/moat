"""
Login via token.
"""

from __future__ import annotations

from moat.lib.micro import Event, L

from ._base import SubAuth as _SubAuth


class SubAuth(_SubAuth):
    """
    Auth method for login via some token.

    Client auth: single string, sent to the server.

    Server auth: a set of strings; the client must send one of them.

    Server config:
        fail_invalid(bool): if True, a client that sends an invalid token
                            is rejected.
    """

    _seen: Event

    async def setup(self):
        "Adds an event, for continuing"
        await super().setup()
        self._seen = Event()

    async def task(self):
        """We want(client) / accept(server) anon auth."""
        if L:
            self.set_ready()

        if self.is_server:
            await self._seen.wait()
        else:
            await self.remote(self.auth)
        self.accept()

    async def cmd(self, token: str):
        """Check token."""

        if token in self.auth:
            self.accept()
        elif self.cfg.get("fail_invalid", False):
            self.deny()
        self._seen.set()
