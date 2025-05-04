"""
An overly-simple CBOR packer/unpacker.
"""

# Original Copyright 2014-2015 Brian Olson
# Apache 2.0 license
# http://docs.ros.org/en/noetic/api/rosbridge_library/html/cbor_8py_source.html
# rather heavily modified

from __future__ import annotations

# Typing
from moat.lib.codec import Extension, NoCodecError
from moat.lib.codec.cbor import Codec, Tag
from moat.lib.codec.proxy import DProxy, Proxy, name2obj, obj2name, unwrap_obj, wrap_obj

from . import NotGiven
from .path import Path

__all__ = ["std_ext", "StdCBOR"]

std_ext = Extension()


class StdCBOR(Codec):
    """
    CBOR codec with MoaT's standard extensions.
    """

    def __init__(self):
        super().__init__(ext=std_ext)

    def decode(self, data:bytes):
        if data == b'':
            return NotGiven
        return super().decode(data)

Codec = StdCBOR


@std_ext.encoder(27, DProxy)
def _enc_dpr(codec, obj):
    codec  # noqa:B018
    res = [obj.name] + obj.a
    if obj.k or res and isinstance(res[-1], dict):
        res.append(obj.k)
    return res


@std_ext.encoder(32769, Proxy)
def _enc_pr(codec, obj):
    codec  # noqa:B018
    return obj.name


@std_ext.decoder(32769)
def _dec_proxy(codec, val):
    codec  # noqa:B018
    try:
        if isinstance(val, (str, int)):
            return name2obj(val)
        return unwrap_obj(val)
    except KeyError:
        return Proxy(val)


@std_ext.decoder(27)
def _dec_obj(codec, val):
    codec  # noqa:B018
    if isinstance(val[0], Tag):
        if val[0].tag != 32769:
            return Tag(27, val)  # not decodable
        val[0] = val[0].value
    return unwrap_obj(val)


@std_ext.encoder(39, Path)
def _enc_path(codec, val):
    codec  # noqa:B018
    return val.raw


@std_ext.decoder(39)
def _dec_path(codec, val):
    codec  # noqa:B018
    if not isinstance(val, (list, tuple)):
        return Tag(39, val)  # not decodable
    return Path.build(val)


@std_ext.encoder(None, object)
def enc_any(codec, obj):
    codec  # noqa:B018

    try:
        name = obj2name(obj)
    except KeyError:
        pass
    else:
        return 32769, name

    try:
        name = obj2name(type(obj))
    except KeyError:
        pass
    else:
        p = wrap_obj(obj, name=name)
        return 27, p

    if isinstance(obj, Exception):
        # RemoteError, cf. moat.lib.codec.errors
        res = ["_rErr", obj.__class__.__name__]
        try:
            res.extend(obj.args)
        except AttributeError:
            pass
        return 27, res

    raise NoCodecError(codec, obj)
