"""
Fake RTC backend for testing.

Provides an RTC class that stores data in memory instead of hardware RTC.
"""

from __future__ import annotations

from moat.util import NotGiven

from . import RTCBase


class RTC(RTCBase):
    """
    Fake RTC backend for testing.

    Stores data in memory. Behaves like mem.py but without hardware.
    """

    is_FS = False
    is_ASYNC = False

    def __init__(self, cfg=None):
        if cfg is None:
            cfg = {}
        super().__init__(cfg)
        self._d = {}

    def reload(self):
        """Reload is a no-op for the fake backend."""
        pass

    async def get(self, name: str):
        """Get a value."""
        if name not in self._d:
            raise KeyError(name)
        return self._d[name]

    async def set(self, name: str, data) -> bool:
        """Set a value."""
        if data is NotGiven:
            self._d.pop(name, None)
        else:
            self._d[name] = data
        return True

    async def all(self):
        """Get all stored data."""
        return dict(self._d)
