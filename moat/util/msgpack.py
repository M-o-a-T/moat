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


from moat.lib.codec.msgpack import Codec

from ._msgpack import std_ext, StdMsgpack

__all__ = ["std_ext", "StdMsgpack"]


Codec = StdMsgpack


@std_ext.encoder(2, int)
def _enc_int(codec, n):
    codec  # noqa:B018
    return n.to_bytes((n.bit_length() + 7) // 8, "big")


@std_ext.decoder(2)
def _dec_bignum(codec, data):
    codec  # noqa:B018
    return int.from_bytes(data, "big")
