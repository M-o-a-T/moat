"bool codec"

from __future__ import annotations

from ._base import Codec as _Codec


class Codec(_Codec):
    """
    A codec that recognizes two strings ("on" and "off") and bool-ifies them.

    Or maybe three ("null") but you need to tell it to do that.
    """

    null: bytes | None = None

    def __init__(self, on="on", off="off", null=None, **kw):
        super().__init__(**kw)
        if on is not None:
            self.on = on.encode("utf-8")
        if off is not None:
            self.off = off.encode("utf-8")
        if null is not None:
            self.null = null.encode("utf-8")

    def encode(self, obj):
        "bool > some text"
        if obj is None and self.null is not None:
            return self.null
        if obj == 0:
            return self.off
        if obj == 1:
            return self.on
        raise ValueError(obj)

    def decode(self, data):
        "some text > bool"
        if data == self.on:
            return True
        if data == self.off:
            return False
        if self.null is not None and data == self.null:
            return None
        raise ValueError(data)
