"""
the WDT doesn't need a server-side command handler
"""

from __future__ import annotations

from moat.lib.rpc import BaseCmd


class Cmd(BaseCmd):
    "empty"

    doc = dict(_c=dict(_d="dummy watchdog"))
    # pylint:disable=unnecessary-pass
