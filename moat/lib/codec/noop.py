"no-op codec"

from __future__ import annotations

from ._base import Codec as _Codec


class Codec(_Codec):
    "no-op codec"

    def __init__(self, ext=None):
        if ext is not None:
            raise ValueError("You can't extend the Null codec")
        super().__init__()
        self._buf = b""

    def encode(self, obj):
        "no-op encode"
        if not obj:
            return b""
        if not isinstance(obj, (bytes, bytearray, memoryview)):
            raise ValueError(obj)  # noqa:TRY004
        return obj

    def decode(self, data):
        "no-op decode"
        return data

    def feed(self, data):
        "no-op feed"
        self._buf += data

    def __next__(self):
        if (buf := self._buf) != b"":
            self._buf = b""
            return buf
        raise StopIteration
