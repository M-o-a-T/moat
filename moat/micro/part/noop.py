"""
fake sensors
"""

from __future__ import annotations

from moat.lib.rpc import BaseCmd

PINS = {}


class NoOp(BaseCmd):
    """
    This is command that does nothing.
    """

    doc = dict(_c=dict(_d="NoOp"))
