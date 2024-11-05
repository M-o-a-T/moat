from ._base import Codec as _Codec, NoCodecError

class Codec(_Codec):
    def __init__(self, ext=None):
        if ext is not None:
            raise ValueError("You can't extend the Null codec")
        super().__init__()

    def encode(self, obj):
        if not isinstance(obj,(bytes,bytearray,memoryview)):
            raise NoCodecError(self, obj)
        return obj

    def decode(self, data):
        return data

    def feed(self, data, final:bool=False):
        return data
