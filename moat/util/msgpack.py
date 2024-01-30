"""
This module contains helper functions for packing+unpacking of single messages,
plus an unpacker factory for streams.

Extension types defined here:
2: contains raw bytes, interpreted as unsigned bignum
3: Path, as a msgpack object stream of its elements
4: contains raw bytes, interpreted as UTF-8, returned as (named) Proxy object
5: object constructor
"""

from __future__ import annotations

from functools import partial

import msgpack

from . import packer, stream_unpacker
from .path import Path
from .proxy import Proxy, _CProxy, obj2name


def _encode(data):
    if isinstance(data, int) and data >= 1 << 64:
        # bignum
        return msgpack.ExtType(2, data.to_bytes((data.bit_length() + 7) // 8, "big"))
    if isinstance(data, Path):
        # Path
        # XXX the mark is dropped until everybody understands type 6
        #   if data.mark:
        #      return msgpack.ExtType(6, packer(data.mark) + b"".join(packer(x) for x in data))
        return msgpack.ExtType(3, b"".join(packer(x) for x in data))
    if isinstance(data, Proxy):
        # Proxy object
        return msgpack.ExtType(5, packer(data.name) + b"".join(packer(x) for x in data.data))
    try:
        name = obj2name(data)
    except KeyError:
        pass
    else:
        return msgpack.ExtType(4, name.encode("utf-8"))

    try:
        name = obj2name(type(data))
    except KeyError:
        pass
    else:
        p = data.__getstate__()
        if not isinstance(p, (list, tuple)):
            p = (p,)
        return msgpack.ExtType(5, packer(name) + b"".join(packer(x) for x in p))

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
            pk = partial(Proxy, pk)
        pk = object.__new__(pk)
        try:
            pk.__setstate__(*s)
        except AttributeError:
            pk.__dict__.update(next(s))
        return pk
    elif code == 6:
        # A marked path
        s = stream_unpacker()
        s.feed(data)
        s = iter(s)
        mark = next(s)
        p = Path(*s)
        p.mark = mark
        return p
    return msgpack.ExtType(code, data)
