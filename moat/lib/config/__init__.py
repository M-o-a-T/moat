"""
Configuration management for MoaT applications.

This module uses lazy loading to avoid circular dependencies.
"""

from __future__ import annotations

from typing import TYPE_CHECKING as _TC

if _TC:
    from ._impl import CFG as CFG
    from ._impl import CfgStore as CfgStore
    from ._impl import current_cfg as current_cfg
    from ._impl import monitor as monitor
    from ._reg import register as register

TEST = False

# Lazy loading for classes and functions
_imports = {
    "CFG": "_impl",
    "CfgStore": "_impl",
    "current_cfg": "_impl",
    "monitor": "_impl",
    "register": "_reg",
}


def __getattr__(attr: str):
    try:
        mod = _imports[attr]
    except KeyError:
        raise AttributeError(attr) from None
    value = getattr(__import__(mod, globals(), None, True, 1), attr)
    globals()[attr] = value
    return value


__all__ = ["CFG", "CfgStore", "current_cfg", "monitor", "register"]
