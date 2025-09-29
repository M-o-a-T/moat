"""
MoaT's command multiplexer.
"""

from __future__ import annotations

from .errors import *  # noqa: F403

from typing import TYPE_CHECKING as _TC

if _TC:
    from .base import Key as Key
    from .base import OptDict as OptDict
