"""
Support for various ICs.

This module uses lazy loading to avoid circular dependencies.
"""

from __future__ import annotations

from typing import TYPE_CHECKING as _TC

if _TC:
    from .hdc2010 import Cmd as hdc2010
    from .tmp102 import Cmd as tmp102

_imports = {
    "hdc2010": ("hdc2010", "Cmd"),
    "tmp102": ("tmp102", "Cmd"),
}


def __getattr__(attr: str):
    try:
        mod, name = _imports[attr]
    except KeyError:
        raise AttributeError(attr) from None
    value = getattr(__import__(mod, globals(), None, True, 1), name)
    globals()[attr] = value
    return value


def __dir__():
    """Expose all lazy-loaded attributes for introspection."""
    return sorted(set(list(__all__) + [k for k in globals().keys() if not k.startswith("_")]))


__all__ = ["hdc2010", "tmp102"]
