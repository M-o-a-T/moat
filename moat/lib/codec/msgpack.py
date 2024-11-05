"""
This module contains helper functions for packing+unpacking of single messages,
plus an unpacker factory for streams.

Extension types defined here:
2: contains raw bytes, interpreted as unsigned bignum
3: Path, as a msgpack object stream of its elements
4: contains raw bytes, interpreted as UTF-8, returned as (named) Proxy object
5: object constructor
6: marked Path
"""

from __future__ import annotations

import msgpack as _msgpack

from ._base import Codec as _Codec

__all__ = ["Codec", "Extension"]

ExtType = _msgpack.ExtType

attrdict = None


class Codec(_Codec):

    def __init__(self, use_attrdict:bool = False, **kw):
        super().__init__(**kw)
        self.use_attrdict = use_attrdict

        if use_attrdict:
            global attrdict
            if attrdict is None:
                from moat.util import attrdict

        self.stream = _msgpack.Unpacker(
            object_pairs_hook=attrdict if use_attrdict else dict,
            strict_map_key=False,
            raw=False,
            use_list=False,
            ext_hook=self._decode,  # pylint:disable=protected-access
    )

    def encode(self, obj):
        return _msgpack.packb(obj, strict_types=False, use_bin_type=True, default=self._encode, **k)

    def _encode(self, obj):
        k,d = self.ext.encode(self, obj)
        return ExtType(k,d)

    def decode(self, data):
        return _msgpack.unpackb(
            data,
            object_pairs_hook=attrdict if self.use_attrdict else dict,
            strict_map_key=False,
            raw=False,
            use_list=False,
            ext_hook=self._decode,  # pylint:disable=protected-access
        )

    def _decode(self, key, data):
        return self.ext.decode(self, key, data)

    def feed(self, data) -> Iterator[Any]:
        self.stream.feed(data)
        return iter(self.stream)
