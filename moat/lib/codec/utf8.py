from codecs import lookup

from ._base import Codec as _Codec
from ._base import NoCodecError

Utf8Stream = lookup("utf-8").incrementaldecoder


class Codec(_Codec):
    def __init__(self, ext=None):
        if ext is not None:
            raise ValueError("You can't extend the UTF8 codec")
        super().__init__()
        self.dec = Utf8Stream()

    def encode(self, obj):
        if not isinstance(obj, str):
            raise NoCodecError(self, obj)
        return obj.encode("utf-8")

    def decode(self, data):
        return data.decode("utf-8")

    def feed(self, data, final: bool = False):
        try:
            return self.dec.decode(data)
        finally:
            if final and (st := self.dec.getstate()) != (b"", 0):
                raise IncompleteData(self, st)
