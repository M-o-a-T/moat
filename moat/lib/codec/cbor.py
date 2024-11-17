"""
This module contains helper functions for packing+unpacking of single messages,
plus an unpacker factory for streams.
"""

from __future__ import annotations

from ._base import Codec as _Codec
from ._base import NoCodecError

import struct

# Typing
from typing import TYPE_CHECKING  # isort:skip

try:
    from micropython import const
except ImportError:

    def const(x: int) -> int:
        return x


if TYPE_CHECKING:
    from typing import Any, Iterator


__all__ = ["Codec", "Tag", "ExtraData"]

attrdict = None


class OutOfData(EOFError):
    "bytes missing"


class Tag:
    "a random CBOR tag"

    def __init__(self, tag=None, value=None):
        self.tag = tag
        self.value = value

    def __repr__(self):
        return f"Tag({self.tag!r}, {self.value!r})"

    def __eq__(self, other):
        if not isinstance(other, Tag):
            return False
        return self.tag == other.tag and self.value == other.value

    def __hash__(self):
        return hash(self.tag) ^ hash(self.value)


# Original Copyright 2014-2015 Brian Olson
# Apache 2.0 license
# http://docs.ros.org/en/noetic/api/rosbridge_library/html/cbor_8py_source.html
# rather heavily modified

CBOR_TYPE_MASK = const(0xE0)  # top 3 bits
CBOR_INFO_BITS = const(0x1F)  # low 5 bits


CBOR_UINT = const(0x00)
CBOR_NEGINT = const(0x20)
CBOR_BYTES = const(0x40)
CBOR_TEXT = const(0x60)
CBOR_ARRAY = const(0x80)
CBOR_MAP = const(0xA0)
CBOR_TAG = const(0xC0)
CBOR_7 = const(0xE0)  # float and other types

CBOR_UINT8_FOLLOWS = const(24)  # 0x18
CBOR_UINT16_FOLLOWS = const(25)  # 0x19
CBOR_UINT32_FOLLOWS = const(26)  # 0x1a
CBOR_UINT64_FOLLOWS = const(27)  # 0x1b
CBOR_VAR_FOLLOWS = const(31)  # 0x1f

CBOR_BREAK = const(0xFF)

CBOR_FALSE = const(CBOR_7 | 20)
CBOR_TRUE = const(CBOR_7 | 21)
CBOR_NULL = const(CBOR_7 | 22)
CBOR_UNDEFINED = const(CBOR_7 | 23)  # js 'undefined' value

CBOR_FLOAT16 = const(CBOR_7 | 25)
CBOR_FLOAT32 = const(CBOR_7 | 26)
CBOR_FLOAT64 = const(CBOR_7 | 27)

# CBOR_TAG_DATE_STRING = const(0) # RFC3339
# CBOR_TAG_DATE_ARRAY = const(1) # any number type follows, seconds since 1970-01-01T00:00:00 UTC
CBOR_TAG_BIGNUM = const(2)  # big endian byte string follows
CBOR_TAG_NEGBIGNUM = const(3)  # big endian byte string follows
# CBOR_TAG_DECIMAL = const(4) # [ 10^x exponent, number ]
# CBOR_TAG_BIGFLOAT = const(5) # [ 2^x exponent, number ]
# CBOR_TAG_BASE64URL = const(21)
# CBOR_TAG_BASE64 = const(22)
# CBOR_TAG_BASE16 = const(23)
# CBOR_TAG_CBOR = const(24) # following byte string is embedded CBOR data

# CBOR_TAG_URI = const(32)
# CBOR_TAG_BASE64URL = const()33
# CBOR_TAG_BASE64 = const(34)
# CBOR_TAG_REGEX = const(35)
# CBOR_TAG_MIME = const(36) # following text is MIME message, headers, separators and all
# CBOR_TAG_CBOR_FILEHEADER = const(55799) # can open a file with 0xd9d9f7

_CBOR_TAG_BIGNUM_BYTES = struct.pack("B", CBOR_TAG | CBOR_TAG_BIGNUM)
_CBOR_TAG_NEGBIGNUM_BYTES = struct.pack("B", CBOR_TAG | CBOR_TAG_NEGBIGNUM)


def _bignum_to_bytearray(val):
    # separate because µPython needs to do this differently
    return val.to_bytes((val.bit_length() + 7) // 8, "big")


class ExtraData(ValueError):
    "buffer contains data beyond end of encoded object"

    def __str__(self):
        return "decoder received extra data."


class Codec(_Codec):
    "Basic CBOR codec"

    _buffer: bytes | bytearray = b""
    _buf_pos: int = 0

    def __init__(self, use_attrdict: bool = False, **kw):
        super().__init__(**kw)
        self.use_attrdict = use_attrdict

        if use_attrdict:
            global attrdict  # noqa: PLW0603
            if attrdict is None:
                from moat.util import attrdict

    def encode(self, obj: Any) -> bytes:
        "pack @obj, return the resulting bytes"
        if self._buffer:
            raise RuntimeError("Codec is busy")

        self._buffer = bytearray()
        try:
            self._enc_any(obj)
            return self._buffer
        finally:
            self._buffer = b""  # always reset

    def decode(self, data: bytes | bytearray | memoryview) -> Any:
        "unpack @data, return the resulting object"
        if self._buffer:
            raise RuntimeError("Codec is busy")

        self._buffer = data
        try:
            res = self._dec_any()
            # chop off the part we've read
            if self._buf_pos != len(data):
                raise ExtraData
            return res
        finally:
            self._buffer = b""  # always reset
            self._buf_pos = 0

    def feed(self, data: bytes | bytearray | memoryview) -> Iterator[Any]:
        "Add additinal input"
        if not self._buffer:
            self._buffer = data
        else:
            if isinstance(self._buffer, (bytearray, memoryview)):
                self._buffer = bytearray(self._buffer)
            self._buffer += data
        return iter(self)

    def _enc_int(self, val):
        "return bytes representing int val in CBOR"
        if val < 0:
            val = -1 - val
            return self._enc_type_num(CBOR_NEGINT, val)
        return self._enc_type_num(CBOR_UINT, val)

    def _enc_float(self, val):
        w = self._w
        try:
            ff = struct.pack("!f", val)
        except OverflowError:
            pass
        else:
            if struct.unpack("!f", ff)[0] == val:  # no loss
                try:
                    fe = struct.pack("!e", val)
                except OverflowError:
                    pass
                else:
                    if struct.unpack("!e", fe)[0] == val:  # no loss either
                        return w(struct.pack("!B", CBOR_FLOAT16) + fe)
                return w(struct.pack("!B", CBOR_FLOAT32) + ff)
        return w(struct.pack("!Bd", CBOR_FLOAT64, val))

    def _enc_type_num(self, cbor_type, val) -> None:
        """
        For some CBOR primary type [0..7] and an auxiliary unsigned
        number, return CBOR encoded bytes
        """
        w = self._w

        if val is None:
            return w(struct.pack("B", cbor_type | CBOR_VAR_FOLLOWS))

        assert val >= 0
        if val <= 23:
            return w(struct.pack("B", cbor_type | val))
        if val <= 0x0FF:
            return w(struct.pack("BB", cbor_type | CBOR_UINT8_FOLLOWS, val))
        if val <= 0x0FFFF:
            return w(struct.pack("!BH", cbor_type | CBOR_UINT16_FOLLOWS, val))
        if val <= 0x0FFFFFFFF:
            return w(struct.pack("!BI", cbor_type | CBOR_UINT32_FOLLOWS, val))
        if val <= 0x0FFFFFFFFFFFFFFFF:
            return w(struct.pack("!BQ", cbor_type | CBOR_UINT64_FOLLOWS, val))

        # too large: write a bignum
        if cbor_type == CBOR_UINT:
            w(_CBOR_TAG_BIGNUM_BYTES)
        elif cbor_type == CBOR_NEGINT:
            w(_CBOR_TAG_NEGBIGNUM_BYTES)
        else:
            raise ValueError("value too big: " + repr(val))
        outb = _bignum_to_bytearray(val)
        self._enc_type_num(CBOR_BYTES, len(outb))
        w(outb)

    def _enc_string(self, val):
        if isinstance(val, str):
            val = val.encode("utf8")
            self._enc_type_num(CBOR_TEXT, len(val))
        else:
            self._enc_type_num(CBOR_BYTES, len(val))
        self._w(val)

    def _enc_array(self, arr):
        try:
            self._enc_type_num(CBOR_ARRAY, len(arr))
        except TypeError:
            self._enc_type_num(CBOR_ARRAY, None)
            for x in arr:
                self._enc_any(x)
            self._w(struct.pack("B", CBOR_BREAK))
        else:
            for x in arr:
                self._enc_any(x)

    def _enc_dict(self, d):
        self._enc_type_num(CBOR_MAP, len(d))
        for k, v in d.items():
            self._enc_any(k)
            self._enc_any(v)

    def _enc_bool(self, b):
        self._w(struct.pack("B", CBOR_TRUE if b else CBOR_FALSE))

    def _enc_tag(self, t, val=...):
        if val is Ellipsis:
            t, val = t.tag, t.value
        self._enc_type_num(CBOR_TAG, t)
        self._enc_any(val)

    def _w(self, d):
        self._buffer.extend(d)

    def _enc_any(self, ob):
        w = self._w
        if ob is None:
            w(struct.pack("B", CBOR_NULL))
        elif ob is Ellipsis:
            w(struct.pack("B", CBOR_UNDEFINED))
        elif isinstance(ob, bool):
            self._enc_bool(ob)
        elif isinstance(ob, (str, bytes)):
            self._enc_string(ob)
        elif isinstance(ob, (list, tuple)):
            self._enc_array(ob)
        # TODO: accept other enumerables and emit a variable length array
        elif isinstance(ob, dict):
            self._enc_dict(ob)
        elif isinstance(ob, float):
            self._enc_float(ob)
        elif isinstance(ob, int):
            self._enc_int(ob)
        elif isinstance(ob, Tag):
            self._enc_tag(ob)
        else:
            self._enc_tag(*self.ext.encode(self, ob))

    # Decoder

    def _read_byte(self):
        return self._read(1)[0]

    def __iter__(self):
        return self

    def __next__(self):
        i = self._buf_pos
        try:
            return self._dec_any()
        except OutOfData:
            self._buf_pos = i
            raise StopIteration from None
        except BaseException:
            self._buf_pos = i
            raise
        finally:
            if len(self._buffer) == self._buf_pos:
                self._buffer = b""
                self._buf_pos = 0

    def _dec_tag_aux(self, tb):
        tag = tb & CBOR_TYPE_MASK
        tag_aux = tb & CBOR_INFO_BITS
        if tag_aux <= 23:
            aux = tag_aux
        elif tag_aux == CBOR_UINT8_FOLLOWS:
            data = self._read(1)
            aux = struct.unpack_from("!B", data, 0)[0]
        elif tag_aux == CBOR_UINT16_FOLLOWS:
            data = self._read(2)
            aux = struct.unpack_from("!H", data, 0)[0]
        elif tag_aux == CBOR_UINT32_FOLLOWS:
            data = self._read(4)
            aux = struct.unpack_from("!I", data, 0)[0]
        elif tag_aux == CBOR_UINT64_FOLLOWS:
            data = self._read(8)
            aux = struct.unpack_from("!Q", data, 0)[0]
        else:
            assert tag_aux == CBOR_VAR_FOLLOWS, f"bogus tag {tb:02x}"
            aux = None

        return tag, aux

    def _read(self, n):
        # (int) -> bytearray
        if (nb := len(self._buffer) - self._buf_pos) < n:
            raise OutOfData(n - nb)
        i = self._buf_pos
        self._buf_pos += n
        return self._buffer[i : i + n]

    def _dec_var_array(self):
        ob = []
        tb = self._read_byte()
        while tb != CBOR_BREAK:
            subob = self._dec_tagged(tb)
            ob.append(subob)
            tb = self._read_byte()
        return ob

    def _dec_var_map(self):
        ob = {}
        tb = self._read_byte()
        while tb != CBOR_BREAK:
            subk = self._dec_tagged(tb)
            subv = self._dec_any()
            ob[subk] = subv
            tb = self._read_byte()
        return ob

    def _dec_array(self, aux):
        ob = []
        for _ in range(aux):
            subob = self._dec_any()
            ob.append(subob)
        return ob

    def _dec_map(self, aux):
        ob = {}
        for _ in range(aux):
            subk = self._dec_any()
            subv = self._dec_any()
            ob[subk] = subv
        return ob

    def _dec_any(self):
        return self._dec_tagged(self._read_byte())

    def _dec_tagged(self, tb):
        # Some special cases of CBOR_7 best handled by special struct.unpack logic here
        if tb == CBOR_FLOAT16:
            data = self._read(2)
            pf = struct.unpack_from("!e", data, 0)
            return pf[0]
        elif tb == CBOR_FLOAT32:
            data = self._read(4)
            pf = struct.unpack_from("!f", data, 0)
            return pf[0]
        elif tb == CBOR_FLOAT64:
            data = self._read(8)
            pf = struct.unpack_from("!d", data, 0)
            return pf[0]

        tag, aux = self._dec_tag_aux(tb)

        if tag == CBOR_UINT:
            return aux
        elif tag == CBOR_NEGINT:
            return -1 - aux
        elif tag == CBOR_BYTES:
            return self._dec_bytes(aux, CBOR_BYTES)
        elif tag == CBOR_TEXT:
            return str(self._dec_bytes(aux, CBOR_TEXT), "utf8")
        elif tag == CBOR_ARRAY:
            if aux is None:
                return self._dec_var_array()
            return self._dec_array(aux)
        elif tag == CBOR_MAP:
            if aux is None:
                return self._var_map()
            return self._dec_map(aux)
        elif tag == CBOR_TAG:
            ob = self._dec_any()
            try:
                return self.ext.decode(self, aux, ob)
            except NoCodecError:
                return Tag(aux, ob)
        else:
            assert tag == CBOR_7
            if tb == CBOR_TRUE:
                return True
            if tb == CBOR_FALSE:
                return False
            if tb == CBOR_NULL:
                return None
            if tb == CBOR_UNDEFINED:
                return Ellipsis
            raise ValueError(f"unknown cbor tag 7 byte: {tb:02x}")

    def _dec_bytes(self, aux, btag):
        # TODO: limit to some maximum number of chunks and some maximum total bytes
        if aux is not None:
            # simple case
            ob = self._read(aux)
            return ob
        # read chunks of bytes
        chunklist = []
        while True:
            tb = self._read_byte()
            if tb == CBOR_BREAK:
                break
            tag, aux = self._dec_tag_aux(tb)
            if tag != btag:
                raise ValueError("var length with unexpected component")
            ob = self._read(aux)
            chunklist.append(ob)
        return b"".join(chunklist)
