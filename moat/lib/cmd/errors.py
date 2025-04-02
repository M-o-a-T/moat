"""
Error classes et al. for moat-lib-cmd.
"""
from __future__ import annotations

from moat.lib.codec.proxy import as_proxy


@as_proxy("_SCmdErr")
class ShortCommandError(ValueError):
    "The command path was too short"

    pass


@as_proxy("_LCmdErr")
class LongCommandError(ValueError):
    "The command path was too long"

    pass
