"""
Proxy helpers for MoaT applications.
"""

from __future__ import annotations

from ._impl import DProxy as DProxy
from ._impl import NoProxyError as NoProxyError
from ._impl import Proxy as Proxy
from ._impl import _CProxy as _CProxy
from ._impl import as_proxy as as_proxy
from ._impl import drop_proxy as drop_proxy
from ._impl import get_proxy as get_proxy
from ._impl import name2obj as name2obj
from ._impl import obj2name as obj2name
from ._impl import unwrap_obj as unwrap_obj
from ._impl import wrap_obj as wrap_obj

__all__ = [
    "DProxy",
    "NoProxyError",
    "Proxy",
    "_CProxy",
    "as_proxy",
    "drop_proxy",
    "get_proxy",
    "name2obj",
    "obj2name",
    "unwrap_obj",
    "wrap_obj",
]
