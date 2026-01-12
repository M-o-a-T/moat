"""
the WDT doesn't need a server-side command handler
"""

from __future__ import annotations

from moat.lib.rpc import BaseCmd


class WDTCmd(BaseCmd):
    "empty"

    # pylint:disable=unnecessary-pass
