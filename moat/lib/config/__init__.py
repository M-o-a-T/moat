"""
Configuration management for MoaT applications.

This module will be refactored in the future.
Currently it re-exports everything from _impl.
"""

from __future__ import annotations

from ._impl import CFG as CFG
from ._impl import CfgStore as CfgStore
from ._impl import current_cfg as current_cfg

TEST = False

__all__ = ["CFG", "CfgStore", "current_cfg"]
