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

from functools import partial

import msgpack as _msgpack

from .dict import attrdict
from .path import Path
from .proxy import Proxy, _CProxy, obj2name, wrap_obj, unwrap_obj, DProxy

__all__ = ["packer", "unpacker", "stream_unpacker"]

try:  # noqa: SIM105
    from . import cbor as _cbor
except ImportError:
    pass

ExtType = _msgpack.ExtType

def _encode(data):
    if isinstance(data, int) and data >= 1 << 64:
        # bignum
        return ExtType(2, data.to_bytes((data.bit_length() + 7) // 8, "big"))
    if isinstance(data, Path):
        # Path
        if data.mark:
            return ExtType(6, packer(data.mark) + b"".join(packer(x) for x in data))
        return ExtType(3, b"".join(packer(x) for x in data))
    if isinstance(data, DProxy):
        # Proxy object with data
        return ExtType(5, b"".join(packer(x) for x in (data.name,data.i,data.s,data.a,data.k)))
    if isinstance(data, Proxy):
        # Proxy object
        return ExtType(5, packer(data.name) + b"".join(packer(x) for x in data.data))

    try:
        name = obj2name(data)
    except KeyError:
        pass
    else:
        return ExtType(4, name.encode("utf-8"))

    try:
        name = obj2name(type(data))
    except KeyError:
        pass
    else:
        p = wrap_obj(data, name=name)
        return ExtType(5, b"".join(packer(x) for x in p))

    # XXX we crash instead of sending an unnamed proxy
    # TODO sending a proxied object a second time will build a new one
    raise ValueError(f"Cannot pack {data !r}")


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
        s = list(iter(s))
        return unwrap_obj(s)

    elif code == 6:
        # A marked path
        s = stream_unpacker()
        s.feed(data)
        s = iter(s)
        mark = next(s)
        p = Path(*s)
        p.mark = mark
        return p
    return ExtType(code, data)


def packer(*a, cbor=False, **k):
    """single message packer"""
    if cbor:
        return _cbor.packb(*a, **k)
    # ruff:noqa:SLF001 pylint:disable=protected-access
    return _msgpack.packb(*a, strict_types=False, use_bin_type=True, default=_encode, **k)


def unpacker(*a, cbor=False, **k):
    """single message unpacker"""
    if cbor:
        return _cbor.unpackb(*a, **k)
    return _msgpack.unpackb(
        *a,
        object_pairs_hook=attrdict,
        strict_map_key=False,
        raw=False,
        use_list=False,
        ext_hook=_decode,  # pylint:disable=protected-access
        **k,
    )


def stream_unpacker(*a, cbor=False, **k):
    """stream unpacker factory"""
    if cbor:
        return _cbor.Unpacker(*a, **k)
    return _msgpack.Unpacker(
        *a,
        object_pairs_hook=attrdict,
        strict_map_key=False,
        raw=False,
        use_list=False,
        ext_hook=_decode,  # pylint:disable=protected-access
        **k,
    )
