from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any

class NoCodecError(ValueError):
    "No codec found"
    pass


class Codec:
    def __init__(self, ext=None):
        self.ext = ext
        self.buf = b""

    def encode(self, obj:Any) -> bytes:
        raise NotImplementedError

    def decode(self, data:Any) -> Any:
        raise NotImplementedError

    def feed(self, data, final:bool = False) -> list[Any]:
        raise NotImplementedError


class Extension:
    binary:bool = None

    def __init__(self):
        self.enc = {}
        self.dec = {}

    def encoder(self, cls: type, key: int, fn) -> None:
        self.enc[type] = (key,fn)

    def decoder(self, key: int, fn) -> None:
        self.dec[type] = fn

    def encode(self, codec, obj):
        try:
            fn = self.enc[type(obj)]
        except KeyError:
            raise NoCodecError(codec, obj) from None
        return fn(codec, obj)

    def decode(self, codec, key, data):
        try:
            fn = self.dec[key]
        except KeyError:
            raise NoCodecError(codec, key) from None
        return fn(key, data)

