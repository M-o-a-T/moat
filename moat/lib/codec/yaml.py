"Basic JSON codec"

from __future__ import annotations

from ._base import Codec as _Codec
from moat.util.compat import byte2utf8
from moat.util import yload, yprint


class Codec(_Codec):
    "basic JSON codec"

    def __init__(self, ext=None):
        if ext is not None:
            raise ValueError("You can't extend the JSON codec")
        super().__init__()
        self._buf = bytearray()

    def encode(self, obj):
        "basic encoder"
        return yprint(obj).encode("utf-8")

    def decode(self, data):
        "basic decoder"
        return yload(data.decode("utf-8"))

    def feed(self, buffer):
        self._buf.extend(buffer)

    def __next__(self):
        i = self._buf.find(b"\n---\n")
        if i < 0:
            raise StopIteration
        res = yload(self._buf[0 : i + 1].decode("utf-8"))
        self._buf[0 : i + 5] = b""
        return res
