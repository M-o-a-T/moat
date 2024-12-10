from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, Callable


class NoCodecError(ValueError):
    "No codec found"


class IncompleteData(ValueError):
    "Stream chopped off"


class Codec:
    def __init__(self, ext=None):
        if ext is None:
            ext = Extension()  # empty
        self.ext = ext
        self.buf = b""

    def encode(self, obj: Any) -> bytes:
        raise NotImplementedError

    def decode(self, data: Any) -> Any:
        raise NotImplementedError

    def feed(self, data, final: bool = False) -> list[Any]:
        raise NotImplementedError


class Extension:
    binary: bool = None

    def __init__(self):
        self.enc: dict[type, tuple[int | None, Callable]] = {}
        self.dec: dict(int, Callable) = {}

    def encoder(self, key: int | None, cls: type, fn=None) -> None:
        def _enc(fn):
            self.enc[cls] = (key, fn)
            return fn

        if fn is None:
            return _enc
        else:
            _enc(fn)

    def decoder(self, key: int, fn=None) -> None:
        def _dec(fn):
            self.dec[key] = fn
            return fn

        if fn is None:
            return _dec
        else:
            _dec(fn)

    def encode(self, codec, obj) -> tuple[int, bytes]:
        try:
            key, fn = self.enc[type(obj)]
        except KeyError:
            try:
                key, fn = self.enc[object]
            except KeyError:
                raise NoCodecError(codec, obj) from None

        res = fn(codec, obj)
        if key is None:
            key, res = res
        return key, res

    def decode(self, codec, key, data):
        try:
            fn = self.dec[key]
        except KeyError:
            raise NoCodecError(codec, key) from None
        return fn(codec, data)
