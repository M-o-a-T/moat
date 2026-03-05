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

    def _seen_evt(self) -> Event:
        "Return the per-instance start/seen event, creating it if needed."
        try:
            return self._seen
        except AttributeError:
            self._seen = Event()
            return self._seen

    async def setup(self):
        "Adds an event, for continuing"
        await super().setup()
        self._seen_evt()

    async def task(self):
        """We want(client) / accept(server) anon auth."""
        if L:
            self.set_ready()

        if self.is_server:
            await self._seen_evt().wait()
        else:
            await self.remote()
        self.accept()

    async def cmd(self):
        """Do nothing."""
        self._seen_evt().set()
