"""
No-op login (always succeeds)
"""

from __future__ import annotations

from moat.lib.micro import L

from ._base import SubAuth as _SubAuth


class SubAuth(_SubAuth):
    """
    Auth method for no login.
    """

    async def task(self):
        """Simply accept."""
        if L:
            self.set_ready()
        self.accept()
