"""
the WDT doesn't need a server-side command handler
"""

from __future__ import annotations

from ._base import BaseAppCmd


class WDTCmd(BaseAppCmd):
    "empty"

    # pylint:disable=unnecessary-pass
