"""
Codec library.
"""

from __future__ import annotations

from ._base import Codec, Extension, NoCodecError

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ._base import ByteType, VarByteType  # noqa:F401


__all__ = ["Codec", "Extension", "NoCodecError", "get_codec"]


def get_codec(codec: str, **kw) -> Codec:
    """
    Loads and initializes the named codec.
    """
    from moat.util import import_  # noqa: PLC0415

    if "." not in codec:
        if codec.startswith("std-"):
            codec = "moat.util." + codec[4:]
        else:
            codec = "moat.lib.codec." + codec
    return import_(codec).Codec(**kw)
