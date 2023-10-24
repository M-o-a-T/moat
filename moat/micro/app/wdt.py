"""
the WDT doesn't need a server-side command handler
"""
from __future__ import annotations

from ._base import BaseAppCmd


class WDTCmd(BaseAppCmd):
    "empty"
    pass  # pylint:disable=unnecessary-pass
