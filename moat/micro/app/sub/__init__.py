"""
Apps used for structure.
"""

from __future__ import annotations

from typing import TYPE_CHECKING as _TC

if _TC:
    from .array import Array as Array
    from .dir import Dir as Dir
    from .err import Err as Err

_imports = {
    "Array": "array",
    "Dir": "dir",
    "Err": "err",
}


def __getattr__(attr: str):
    try:
        mod = _imports[attr]
    except KeyError:
        raise AttributeError(attr) from None
    value = getattr(__import__(mod, globals(), None, True, 1), attr)
    globals()[attr] = value
    return value


def __dir__():
    """Expose all lazy-loaded attributes for introspection."""
    return sorted(set(list(__all__) + [k for k in globals().keys() if not k.startswith("_")]))


__all__ = ["Array", "Dir", "Err"]
