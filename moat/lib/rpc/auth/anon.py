"""
Anonymous login.
"""

from __future__ import annotations

from moat.lib.micro import Event, L

from ._base import SubAuth as _SubAuth


class SubAuth(_SubAuth):
    """
    Auth method for anonymous login.
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
            await self.remote()
        self.accept()

    async def cmd(self):
        """Do nothing."""
        self._seen.set()
