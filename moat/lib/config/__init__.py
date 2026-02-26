"""
Configuration management for MoaT applications.

This module uses lazy loading to avoid circular dependencies.
"""

from __future__ import annotations

from importlib import import_module

from typing import TYPE_CHECKING as _TC

if _TC:
    from ._impl import CFG as CFG
    from ._impl import CFG_ as CFG_
    from ._impl import CfgStore as CfgStore
    from ._impl import current_cfg as current_cfg
    from ._impl import load_yaml as load_yaml
    from ._impl import monitor as monitor
    from ._reg import register as register

TEST = False

# Lazy loading for classes and functions
_imports: dict[str, str] = {
    "CFG": "_impl",
    "CFG_": "_impl",
    "CfgStore": "_impl",
    "current_cfg": "_impl",
    "load_yaml": "_impl",
    "monitor": "_impl",
    "register": "_reg",
}


def __getattr__(attr: str) -> object:
    try:
        mod = _imports[attr]
    except KeyError:
        raise AttributeError(attr) from None
    module = import_module(f".{mod}", __name__)
    value = getattr(module, attr)
    globals()[attr] = value
    return value


def __dir__() -> list[str]:
    """Expose all lazy-loaded attributes for introspection."""
    return sorted(set(list(__all__) + [k for k in globals().keys() if not k.startswith("_")]))


__all__ = ["CFG", "CFG_", "CfgStore", "current_cfg", "load_yaml", "monitor", "register"]
