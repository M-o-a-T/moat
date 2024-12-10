"no-op codec"

from __future__ import annotations

from ._base import Codec as _Codec
from ._base import NoCodecError


class Codec(_Codec):
    "no-op codec"

    def __init__(self, ext=None):
        if ext is not None:
            raise ValueError("You can't extend the Null codec")
        super().__init__()

    def encode(self, obj):
        "no-op encode"
        if not isinstance(obj, (bytes, bytearray, memoryview)):
            raise NoCodecError(self, obj)
        return obj

    def decode(self, data):
        "no-op decode"
        return data

    def feed(self, data, final: bool = False):  # noqa: ARG002
        "no-op feed"
        return data
