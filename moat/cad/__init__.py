"""
This module contains code to support Build123d.
"""

from __future__ import annotations

try:
    from .lib import *  # noqa:F403
except ImportError:
    pass

from moat.util.config import CfgStore

CfgStore.with_(__name__)
