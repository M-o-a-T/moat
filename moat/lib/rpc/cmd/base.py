"""
Basic command handling in MoaT-RPC.
"""

from __future__ import annotations

from ._base import BaseCmd as BaseCmd
from ._base import LoadCmd as LoadCmd
from ._base import LockBaseCmd as LockBaseCmd
from ._base import RootCmd as _RootCmd

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.lib.path import Path


class RootCmd(_RootCmd):
    """
    This is the system's root dispatcher.

    This class ducktypes :py:class:`~moat.lib.rpc.cmd._base.BaseCmd`.
    """

    def cfg_at(self, p: Path):
        "returns a CfgStore object at this subpath"
        from moat.lib.rpc.cmd.tree.dir import CfgStore  # noqa:PLC0415

        return CfgStore(self, p)
