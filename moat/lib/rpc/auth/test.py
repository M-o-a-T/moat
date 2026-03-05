"""
Test auth.
"""

from __future__ import annotations

from moat.lib.micro import Event, L

from ._base import SubAuth as _SubAuth


class SubAuth(_SubAuth):
    """
    Auth method for testing.

    It requires an 'ok' parameter that gets forwarded to the remote side.

    True/False/None means Accept/Deny/Ignore. Ignore is the default.
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
        """Handle this auth method."""
        if L:
            self.set_ready()

        if self.is_server:
            await self._seen_evt().wait()
            return

        ok = self.auth.get("ok", self.parent.cfg.get("ok", self.cfg.get("ok")))
        res = await self.remote.test(ok)
        if res:
            self.accept()
        elif res is False:
            self.deny()
        # otherwise do nothing

        return

    async def cmd_test(self, ok=None):
        """Handle receiving a request for this auth method"""
        self._seen_evt().set()
        if ok is True:
            self.accept()
        elif ok is False:
            self.deny()
        return ok
