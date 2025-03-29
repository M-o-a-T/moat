"""
Codec library.
"""

from __future__ import annotations

from ._base import Codec, Extension, NoCodecError


__all__ = ["Codec", "Extension", "get_codec", "NoCodecError"]


def get_codec(codec=None, **kw) -> Codec:
    """
    Loads and initializes the named codec.
    """
    from moat.util import import_

    if "." not in codec:
        if codec.startswith("std-"):
            codec = "moat.util." + codec[4:]
        else:
            codec = "moat.lib.codec." + codec
    return import_(codec).Codec(**kw)
