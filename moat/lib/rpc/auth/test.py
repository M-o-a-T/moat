"""
Test auth.
"""

from __future__ import annotations

from moat.lib.micro import L

from ._base import SubAuth as _SubAuth


class SubAuth(_SubAuth):
    """
    Auth method for testing.

    It requires an 'ok' parameter that gets forwarded to the remote side.

    True/False/None means Accept/Deny/Ignore. Ignore is the default.
    """

    async def task(self):
        """Handle this auth method."""
        if L:
            self.set_ready()

        if self.is_server:
            return
        ok = self.auth.get("ok", self.parent.cfg.get("ok", self.cfg.get("ok")))
        res = await self.remote.test(ok)
        if res.kw:
            res = res.kw.get("r", None)
        elif res.args:
            res = res.args[0]
        else:
            res = None

        if res:
            self.accept()
        elif res is False:
            self.deny()
        # otherwise do nothing

        return

    async def cmd_test(self, ok=None):
        """Handle receiving a request for this auth method"""
        if ok is True:
            self.accept()
        elif ok is False:
            self.deny()
        return ok
