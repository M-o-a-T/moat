"""
This module contains extension handlers for msgpack.

Extension types defined here:
2: contains raw bytes, interpreted as unsigned bignum
3: Path, as a msgpack object stream of its elements
4: contains raw bytes, interpreted as UTF-8, returned as (named) Proxy object
5: object constructor
6: marked Path
"""

from __future__ import annotations

import moat.lib.codec.msgpack as _msgpack

from moat.lib.codec import Extension, NoCodecError
from moat.lib.codec.msgpack import Codec
from moat.lib.codec.proxy import DProxy, Proxy, _CProxy, obj2name, unwrap_obj, wrap_obj
from moat.util.compat import log

from .path import Path

__all__ = ["std_ext", "StdMsgpack"]


std_ext = Extension()
ExtType = _msgpack.ExtType


class StdMsgpack(Codec):
    "A MsgPack codec with our extensions"

    def __init__(self):
        super().__init__(ext=std_ext, use_attrdict=True)


Codec = StdMsgpack


@std_ext.encoder(5, DProxy)
def _enc_dproxy(codec, obj):
    a = obj.a[:]
    if obj.k or a and isinstance(a[-1], dict):
        a.append(obj.k)
    return codec.encode(obj.name) + b"".join(codec.encode(x) for x in a)


# not actually used
@std_ext.encoder(None, ExtType)
def _enc_exttype(codec, obj):
    codec  # noqa:B018
    return obj.type, obj.data


@std_ext.encoder(None, Path)
def _enc_path(codec, obj):
    if obj.mark:
        return 6, codec.encode(obj.mark) + b"".join(codec.encode(x) for x in obj)
    return 3, b"".join(codec.encode(x) for x in obj)


@std_ext.encoder(4, Proxy)
def _enc_proxy(codec, obj):
    return obj.name.encode("utf-8")


@std_ext.encoder(None, object)
def _enc_any(codec, obj):
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
        return 5, b"".join(codec.encode(x) for x in p)

    if isinstance(obj, Exception):
        # RemoteError, cf. moat.lib.codec.errors
        return 5, codec.encode("_rErr") + codec.encode(obj.__class__.__name__) + b"".join(
            codec.encode(x) for x in obj.args
        )

    raise NoCodecError(codec, obj)


@std_ext.decoder(3)
def _dec_path(codec, data):
    codec  # noqa:B018
    s = Codec()
    s.feed(data)
    return Path(*iter(s))


@std_ext.decoder(4)
def _dec_proxy(codec, data):
    codec  # noqa:B018
    if isinstance(data, memoryview):
        data = bytearray(data)
    try:
        n = data.decode("utf-8")
    except UnicodeError:
        n = str(data)
    try:
        return _CProxy[n]
    except KeyError:
        return Proxy(n)


@std_ext.decoder(5)
def _dec_proxy_obj(codec, data):
    codec = codec.copy()
    codec.feed(data)
    s = list(iter(codec))
    return unwrap_obj(s)


@std_ext.decoder(6)
def _dec_marked_path(codec, data):
    # A marked path. Deprecated.
    codec = codec.copy()
    codec.feed(data)
    s = iter(codec)
    mark = next(s)
    p = Path(*s)
    p.mark = mark
    return p


@std_ext.decoder(None)
def _dec_blank(codec, data):
    return ExtType(codec, data)
