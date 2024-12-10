"""
UTF-8 codec
"""

from __future__ import annotations

from ._base import Codec as _Codec
from ._base import NoCodecError, IncompleteData

from codecs import lookup

Utf8Stream = lookup("utf-8").incrementaldecoder


class Codec(_Codec):
    "Basic UTF-8 codec"

    def __init__(self, ext=None):
        if ext is not None:
            raise ValueError("You can't extend the UTF8 codec")
        super().__init__()
        self.dec = Utf8Stream()

    def encode(self, obj):
        "Encode UTF-8 to bytestring"
        if not isinstance(obj, str):
            raise NoCodecError(self, obj)
        return obj.encode("utf-8")

    def decode(self, data):
        "Decode a bytestring to UTF-8"
        return data.decode("utf-8")

    def feed(self, data, final: bool = False):
        """
        Add to-be-decoded data.

        Returns the string found so far (i.e. without incomplete UTF-8 codes).
        """
        try:
            return self.dec.decode(data)
        finally:
            if final and (st := self.dec.getstate()) != (b"", 0):
                raise IncompleteData(self, st)
