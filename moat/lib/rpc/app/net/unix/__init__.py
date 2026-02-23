"""
Apps for Unix socket connectivity.
"""

from __future__ import annotations

from typing import TYPE_CHECKING as _TC

if _TC:
    from .link import Link as Link
    from .linkin import LinkIn as LinkIn
    from .port import Port as Port
    from .raw import Raw as Raw

_imports = {
    "Link": "link",
    "LinkIn": "linkin",
    "Port": "port",
    "Raw": "raw",
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


__all__ = ["Link", "LinkIn", "Port", "Raw"]
