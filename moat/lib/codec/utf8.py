"""
UTF-8 codec
"""

from __future__ import annotations

from moat.util.compat import byte2utf8

from ._base import Codec as _Codec

try:
    from codecs import lookup
except ImportError:
    Utf8Stream = None
else:
    Utf8Stream = lookup("utf-8").incrementaldecoder

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.lib.codec import ByteType


class Codec(_Codec):
    "Basic UTF-8 codec"

    def __init__(self, ext=None):
        if ext is not None:
            raise ValueError("You can't extend the UTF8 codec")
        super().__init__()
        if Utf8Stream is not None:
            self.dec = Utf8Stream()
        self._buf: str = ""

    def encode(self, obj) -> ByteType:
        "Encode UTF-8 to bytestring"
        if not isinstance(obj, str):
            raise ValueError(self, obj)  # noqa:TRY004
        return obj.encode("utf-8")

    def decode(self, data: ByteType) -> str:
        "Decode a bytestring to UTF-8"
        return byte2utf8(data)

    def feed(self, data: ByteType):
        """
        Add to-be-decoded data.

        Returns the string found so far (i.e. without incomplete UTF-8 codes).
        """
        self._buf += self.dec.decode(data)

    def __next__(self):
        if (buf := self._buf) != "":
            self._buf = ""
            return buf
        raise StopIteration
