"""
Stream support for MoaT RPC.
"""

from __future__ import annotations

# Re-export everything from base for backward compatibility
from .base import *  # noqa: F403

# Import and re-export from cmdbbm, cmdmsg, xcmd
from .cmdbbm import *  # noqa: F403
from .cmdmsg import *  # noqa: F403
from .xcmd import *  # noqa: F403

__all__ = []

# Collect __all__ from all submodules
from . import base, cmdbbm, cmdmsg, xcmd

for mod in (base, cmdbbm, cmdmsg, xcmd):
    if hasattr(mod, "__all__"):
        __all__ += mod.__all__
