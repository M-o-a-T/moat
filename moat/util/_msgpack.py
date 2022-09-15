"""
This module contains helper functions for packing+unpacking of single messages,
plus an unpacker factory for streams.

Extension types defined here:
2: contains raw bytes, interpreted as unsigned bignum
3: Path, as a msgpack object stream of its elements
4: contains raw bytes, interpreted as UTF-8, returned as (named) Proxy object
"""

from functools import partial

import msgpack

from ._dict import attrdict
from ._path import Path

__all__ = ["packer", "unpacker", "stream_unpacker", "Proxy"]


class Proxy:
    """
    A proxy object, i.e. a placeholder for things that cannot pass through MsgPack.
    """

    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return f"{self.__class__.__name__}({self.name !r})"


def _encode(data):
    if isinstance(data, int) and data >= 1 << 64:
        return msgpack.ExtType(2, data.to_bytes((data.bit_length() + 7) // 8, "big"))
    elif isinstance(data, Path):
        return msgpack.ExtType(3, b"".join(packer(x) for x in data))
    elif isinstance(data, Proxy):
        return msgpack.ExtType(4, data.name.encode("utf-8"))
    return data


def _decode(code, data):
    if code == 2:
        return int.from_bytes(data, "big")
    elif code == 3:
        s = stream_unpacker()
        s.feed(data)
        return Path(*s)
    elif code == 4:
        try:
            return Proxy(data.decode("utf-8"))
        except UnicodeDecodeError:
            return Proxy(str(data))
    return msgpack.ExtType(code, data)


# single message packer
packer = partial(msgpack.packb, strict_types=False, use_bin_type=True, default=_encode)

# single message unpacker
unpacker = partial(
    msgpack.unpackb,
    object_pairs_hook=attrdict,
    strict_map_key=False,
    raw=False,
    use_list=False,
    ext_hook=_decode,
)

# stream unpacker factory
stream_unpacker = partial(
    msgpack.Unpacker,
    object_pairs_hook=attrdict,
    strict_map_key=False,
    raw=False,
    use_list=False,
    ext_hook=_decode,
)
