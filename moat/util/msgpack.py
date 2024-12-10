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

from moat.lib.codec import Extension, NoCodecError
from moat.lib.codec.msgpack import Codec
from moat.lib.codec.proxy import DProxy, Proxy, _CProxy, obj2name, unwrap_obj, wrap_obj

from .path import Path

__all__ = ["packer", "unpacker", "stream_unpacker", "std_ext", "StdMsgpack"]


std_ext = Extension()
ExtType = _msgpack.ExtType


class StdMsgpack(Codec):
    "A MsgPack codec with our extensions"

    def __init__(self):
        super().__init__(ext=std_ext, use_attrdict=True, use_list=False)


Codec = StdMsgpack


@std_ext.encoder(2, int)
def _enc_int(codec, n):
    codec  # noqa:B018
    return n.to_bytes((n.bit_length() + 7) // 8, "big")


@std_ext.encoder(5, DProxy)
def _enc_dproxy(codec, obj):
    codec  # noqa:B018
    return b"".join(packer(getattr(obj, x)) for x in ("name", "i", "s", "a", "k"))


# not actually used
@std_ext.encoder(None, ExtType)
def _enc_exttype(codec, obj):
    codec  # noqa:B018
    return obj.type, obj.data


@std_ext.encoder(None, Path)
def _enc_path(codec, obj):
    codec  # noqa:B018
    if obj.mark:
        return 6, packer(obj.mark) + b"".join(packer(x) for x in obj)
    return 3, b"".join(packer(x) for x in obj)


@std_ext.encoder(5, Proxy)
def _enc_proxy(codec, obj):
    codec  # noqa:B018
    return packer(obj.name) + b"".join(packer(x) for x in obj.data)


@std_ext.encoder(None, object)
def _enc_any(codec, obj):
    codec  # noqa:B018
    try:
        name = obj2name(obj)
    except KeyError:
        pass
    else:
        return 4, name.encode("utf-8")

    try:
        name = obj2name(type(obj))
    except KeyError:
        pass
    else:
        p = wrap_obj(obj, name=name)
        return 5, b"".join(packer(x) for x in p)

    raise NoCodecError(codec, obj)


@std_ext.decoder(2)
def _dec_bignum(codec, data):
    codec  # noqa:B018
    return int.from_bytes(data, "big")


@std_ext.decoder(3)
def _dec_path(codec, data):
    codec  # noqa:B018
    s = Codec()
    p = s.feed(data)
    return Path(*p)


@std_ext.decoder(4)
def _dec_proxy(codec, data):
    codec  # noqa:B018
    try:
        n = data.decode("utf-8")
    except UnicodeDecodeError:
        n = str(data)
    try:
        return _CProxy[n][0]
    except KeyError:
        return Proxy(n)


@std_ext.decoder(5)
def _dec_proxy_obj(codec, data):
    codec  # noqa:B018
    s = stream_unpacker()
    s.feed(data)
    s = list(iter(s))
    return unwrap_obj(s)


@std_ext.decoder(6)
def _dec_marked_path(codec, data):
    codec  # noqa:B018
    # A marked path
    s = stream_unpacker()
    s.feed(data)
    s = iter(s)
    mark = next(s)
    p = Path(*s)
    p.mark = mark
    return p


@std_ext.decoder(None)
def _dec_blank(codec, data):
    return ExtType(codec, data)


def packer(obj):
    """
    Packer for single msgpack-coded messages.

    Deprecated.
    """
    return Codec().encode(obj)


def unpacker(obj):
    """
    Unpacker for single msgpack-coded messages.

    Deprecated.
    """
    return Codec().decode(obj)


class StreamUnpacker:
    """
    A helper class that maps the old unpacker interface (separate
    feed/iterator methods) to the new one (``feed`` returns the iterator).
    """

    def __init__(self, **kw):
        self.codec = Codec(**kw)
        self.res = []

    def __iter__(self):
        return self

    def __next__(self):
        if not self.res:
            raise StopIteration
        res, self.res = self.res[0], self.res[1:]
        return res

    def feed(self, data: bytes):
        self.res.extend(self.codec.feed(data))


def stream_unpacker():
    """
    Create a streamed MsgPack unpacker.

    Deprecated.
    """
    return StreamUnpacker()
