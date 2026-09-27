"Basic JSON codec"

from __future__ import annotations

from moat.util import yload, yprint

from ._base import Codec as _Codec

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ._base import ByteType


class Codec(_Codec):
    "basic JSON codec"

    def __init__(self, ext=None):
        if ext is not None:
            raise ValueError("You can't extend the JSON codec")
        super().__init__()
        self._buf = bytearray()
        self._eof = False

    def encode(self, obj):
        "basic encoder"
        return yprint(obj).encode("utf-8", "surrogateescape")

    def decode(self, data):
        "basic decoder"
        return yload(data.decode("utf-8", "surrogateescape"))

    def feed(self, data: ByteType) -> None:  # noqa: D102
        self._buf.extend(data)

    def eof(self) -> None:  # noqa: D102
        self._eof = True

    def __next__(self):
        i = self._buf.find(b"\n---\n")
        if i >= 0:
            res = yload(self._buf[0 : i + 1].decode("utf-8", "surrogateescape"))
            self._buf[0 : i + 5] = b""
            return res
        if not self._eof:
            raise StopIteration

        # last document, not terminated by "---"
        rest = bytes(self._buf).strip()
        self._buf.clear()
        if rest.endswith(b"\n---"):
            rest = rest[:-4]
        if not rest or rest == b"---":
            raise StopIteration
        return yload(rest.decode("utf-8", "surrogateescape"))
