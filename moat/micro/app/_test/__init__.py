"""
Apps used for testing.

This module uses lazy loading to avoid circular dependencies.
"""

from __future__ import annotations

from typing import TYPE_CHECKING as _TC

if _TC:
    from .loopcmd import LoopCmd as LoopCmd
    from .looplink import LoopLink as LoopLink
    from .loopmsg import LoopMsg as LoopMsg
    from .mpycmd import MpyCmd as MpyCmd
    from .mpyraw import MpyRaw as MpyRaw

# Re-export from _test_ for backwards compatibility
from moat.lib.rpc.app._test_ import Cmd as Cmd
from moat.lib.rpc.app._test_ import Cons as Cons

_imports = {
    "LoopCmd": "loopcmd",
    "LoopLink": "looplink",
    "LoopMsg": "loopmsg",
    "MpyCmd": "mpycmd",
    "MpyRaw": "mpyraw",
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


__all__ = ["Cmd", "Cons", "LoopCmd", "LoopLink", "LoopMsg", "MpyCmd", "MpyRaw"]
