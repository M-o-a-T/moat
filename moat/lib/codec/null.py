"""Null codec — accepts only ``None``.

This codec exists as a placeholder, e.g. for use in conversion-vector
trees to mark paths whose payload should be silently dropped by gateways.
It encodes ``None`` to an empty byte string and refuses any other value.
Decoding ignores the input and returns ``None``.
"""

from __future__ import annotations

from ._base import Codec as _Codec

from typing import Any


class Codec(_Codec):
    """Codec that only accepts :data:`None` as a value."""

    def __init__(self, ext: Any | None = None) -> None:
        if ext is not None:
            raise ValueError("You can't extend the null codec")
        super().__init__()

    def encode(self, obj: Any) -> bytes:
        """Encode :data:`None` to empty bytes; raise otherwise."""
        if obj is None:
            return b""
        raise ValueError(f"The null codec only accepts None, not {obj!r}")

    def decode(self, data: bytes | bytearray | memoryview) -> None:  # noqa: ARG002
        """Discard ``data`` and return :data:`None`."""
        return None
