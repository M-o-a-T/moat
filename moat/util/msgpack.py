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

from .dict import attrdict
from .path import Path
from .impl import NotGiven

__all__ = ["packer", "unpacker", "stream_unpacker", "Proxy", "NoProxyError", "as_proxy"]


class Proxy:
    """
    A proxy object, i.e. a placeholder for things that cannot pass through MsgPack.
    """

    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return f"{self.__class__.__name__}({self.name !r})"


class NoProxyError(ValueError):
    "Error for nonexistent proxy values"
    pass  # pylint:disable=unnecessary-pass

class ProxyObj:
    def __init__(self, name, *data):
        self.name = name
        self.data = data

    def __repr__(self):
        return f"RemoteObj('{self.name}',"+",".join(repr(x) for x in data)+")"

# _pkey = 1
_CProxy:dict[str,object] = {}
_RProxy:dict[int,str] = {}

def as_proxy(name):
    """
    Export an object or class as a named proxy.
    """
    def _proxy(obj):
        _CProxy[name] = obj
        _RProxy[id(obj)] = name
        return obj
    return _proxy

as_proxy("-")(NotGiven)

def _encode(data):
    if isinstance(data, int) and data >= 1 << 64:
        # bignum
        return msgpack.ExtType(2, data.to_bytes((data.bit_length() + 7) // 8, "big"))
    elif isinstance(data, Path):
        # Path
        return msgpack.ExtType(3, b"".join(packer(x) for x in data))
    elif isinstance(data, Proxy):
        # Proxy object
        return msgpack.ExtType(4, data.name.encode("utf-8"))
    elif isinstance(data, ProxyObj):
        # proxy class
        return msgpack.ExtType(5, packb(data.name) + b"".join(packb(x) for x in data.data))
    elif id(data) in _RProxy:
        # already-proxied object
        return msgpack.ExtType(4, _RProxy[id(data)].encode("utf-8"))
    elif id(type(data)) in _RProxy:
        # to-be-proxied object
        p = data.__getstate__()
        if not isinstance(p,(list,tuple)):
            p = (p,)
        return msgpack.ExtType(5, packer(_RProxy[id(type(data))]) + b"".join(packer(x) for x in p))

    # XXX we crash instead of sending an unnamed proxy
    # TODO sending a proxied object a second time will build a new one
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
            n = data.decode("utf-8")
        except UnicodeDecodeError:
            n = str(data)
        try:
            return _CProxy[n]
        except KeyError:
            return Proxy(n)
    elif code == 5:
        s = stream_unpacker()
        s.feed(data)
        s = iter(s)
        pk = next(s)
        try:
            pk = _CProxy[pk]
        except KeyError:
            pk = partial(RemoteObj,pk)
        pk = object.__new__(pk)
        try:
            pk.__setstate__(*s)
        except AttributeError:
            pk.__dict__.update(next(s))
        return pk
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
