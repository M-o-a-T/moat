"""
Codec library.
"""

from __future__ import annotations

from ._base import Codec, Extension, NoCodecError


__all__ = ["Codec", "Extension", "get_codec", "get_ext", "NoCodecError"]


def get_codec(name, *a, **kw) -> Codec:
    from importlib import import_module

    if "." not in name:
        name = "moat.lib.codec." + name
    return import_module(name).Codec(*a, **kw)