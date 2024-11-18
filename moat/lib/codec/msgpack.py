"""
This module contains "MoaT-standard" helper functions for packing+unpacking
of single messages, plus an unpacker factory for streams.
"""

from __future__ import annotations

import msgpack as _msgpack

from ._base import Codec as _Codec
from ._base import NoCodecError

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, Iterator

__all__ = ["Codec", "ExtType"]

ExtType = _msgpack.ExtType

attrdict = None


class Codec(_Codec):
    "Extensible msgpack codec"

    def __init__(self, use_attrdict: bool = False, use_list=True, **kw):
        # TODO add keywords for msgpack enc/dec settings
        super().__init__(**kw)
        self.use_attrdict = use_attrdict
        self.use_list = use_list

        if use_attrdict:
            global attrdict  # noqa: PLW0603
            if attrdict is None:
                from moat.util import attrdict

        self.stream = _msgpack.Unpacker(
            object_pairs_hook=attrdict if use_attrdict else dict,
            strict_map_key=False,
            raw=False,
            use_list=self.use_list,
            ext_hook=self._decode,  # pylint:disable=protected-access
        )

    def encode(self, obj):
        "object > bytes"
        return _msgpack.packb(obj, strict_types=False, use_bin_type=True, default=self._encode)

    def _encode(self, obj):
        k, d = self.ext.encode(self, obj)
        return ExtType(k, d)

    def decode(self, data):
        "bytes > object"
        return _msgpack.unpackb(
            data,
            object_pairs_hook=attrdict if self.use_attrdict else dict,
            strict_map_key=False,
            raw=False,
            use_list=self.use_list,
            ext_hook=self._decode,  # pylint:disable=protected-access
        )

    def _decode(self, key, data):
        try:
            return self.ext.decode(self, key, data)
        except NoCodecError:
            return ExtType(key, data)

    def feed(self, data) -> Iterator[Any]:
        "Add more bytes. Returns an iterator for the result."
        self.stream.feed(data)
        return iter(self.stream)
