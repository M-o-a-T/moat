"""
This is a micropython-compatible MsgPack implementation.
It does not support
* a "default" fallback encoder
* encoding binary data to strings (which is legacy nonsense anyway)
* auto-encoding datetime to the timestamp extension
* the object_pairs hook

The encoder returns bytes.
The decoder yields messages.
You can also decode single messages.

The decoder returns binary data as memoryviews if they're larger
than the threshold (default -1: always copy). Extension objects always
get a memoryview and must decode or copy it.
"""

from __future__ import annotations

import struct
import sys
from io import BytesIO

from moat.util import OutOfData, attrdict
from moat.util.compat import byte2utf8, const

from ._base import Codec as _Codec
from ._base import NoCodecError

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from ._base import ByteType, VarByteType

__all__ = ["Codec", "ExtType"]


class Codec(_Codec):
    "Extensible msgpack codec"

    def __init__(self, use_attrdict: bool = False, **kw):
        # TODO add keywords for msgpack enc/dec settings
        super().__init__(**kw)
        self.use_attrdict = use_attrdict
        self.__kw = kw

        self.stream = Unpacker(
            ext_hook=self._decode,  # pyright:ignore
            use_attrdict=use_attrdict,
        )

    def copy(self) -> Codec:
        "copy me"
        return Codec(use_attrdict=self.use_attrdict, **self.__kw)

    def encode(self, obj):
        "object > bytes"
        return packb(obj, default=self._encode)

    def _encode(self, obj):
        k, d = self.ext.encode(self, obj)
        return ExtType(k, d)

    def decode(self, data: ByteType):
        "bytes > object"
        return unpackb(
            data,
            ext_hook=self._decode,
            use_attrdict=self.use_attrdict,
        )

    def _decode(self, key, data):
        try:
            return self.ext.decode(self, key, data)
        except NoCodecError:
            return ExtType(key, data)

    def feed(self, data):
        "Add more bytes. Returns an iterator for the result."
        self.stream.feed(data)

    def __iter__(self):
        return self

    def __next__(self):
        return next(self.stream)

    def unfeed(self, buf: VarByteType | None) -> int:
        "Take from the decoder's buffer."
        return self.stream.unfeed(buf)


# cloned from https://github.com/msgpack/msgpack-python

# Parts of this have been modified to be compatble with micropython.


class UnpackException(Exception):
    "superclass, not raised"


class FormatError(UnpackException):
    "Error code read"


class ExtraData(ValueError):
    "too much data in buffer"

    def __init__(self, unpacked, extra):
        self.unpacked = unpacked
        self.extra = extra

    def __str__(self):
        return "unpack(b) received extra data."


class ExtType:
    """ExtType represents extension types in msgpack."""

    def __init__(self, code, data):
        if isinstance(data, memoryview):
            data = bytes(data)
        self.code = code
        self.data = data

    def __repr__(self):
        return f"Ext({self.code}:{self.data})"


_TYPE_IMMEDIATE = const(0)
_TYPE_ARRAY = const(1)
_TYPE_MAP = const(2)
_TYPE_RAW = const(3)
_TYPE_BIN = const(4)
_TYPE_EXT = const(5)

DEFAULT_RECURSE_LIMIT = 20


_MSGPACK_HEADERS = {
    0xC4: (1, "", _TYPE_BIN),
    0xC5: (2, ">H", _TYPE_BIN),
    0xC6: (4, ">I", _TYPE_BIN),
    0xC7: (2, "Bb", _TYPE_EXT),
    0xC8: (3, ">Hb", _TYPE_EXT),
    0xC9: (5, ">Ib", _TYPE_EXT),
    0xCA: (4, ">f"),
    0xCB: (8, ">d"),
    0xCC: (1, ""),
    0xCD: (2, ">H"),
    0xCE: (4, ">I"),
    0xCF: (8, ">Q"),
    0xD0: (1, "b"),
    0xD1: (2, ">h"),
    0xD2: (4, ">i"),
    0xD3: (8, ">q"),
    0xD4: (1, "b1s", _TYPE_EXT),
    0xD5: (2, "b2s", _TYPE_EXT),
    0xD6: (4, "b4s", _TYPE_EXT),
    0xD7: (8, "b8s", _TYPE_EXT),
    0xD8: (16, "b16s", _TYPE_EXT),
    0xD9: (1, "", _TYPE_RAW),
    0xDA: (2, ">H", _TYPE_RAW),
    0xDB: (4, ">I", _TYPE_RAW),
    0xDC: (2, ">H", _TYPE_ARRAY),
    0xDD: (4, ">I", _TYPE_ARRAY),
    0xDE: (2, ">H", _TYPE_MAP),
    0xDF: (4, ">I", _TYPE_MAP),
}


class Unpacker:
    """
    Manager for buffered and streamed unpacking.
    """

    def __init__(
        self,
        ext_hook=ExtType,
        use_attrdict=False,
        min_memview_len=-1,
    ):
        #: array of bytes fed.
        self._buffer = bytearray()
        #: Which position we currently reads
        self._buf_pos = 0

        self._ext_hook = ext_hook
        self._min_memview_len = min_memview_len
        self._use_attrdict = use_attrdict

    def feed(self, data):
        "set the buffer"
        if self._buffer and self._buf_pos < len(self._buffer):
            if self._buf_pos == 0:
                self._buffer += data
                return
            data = self._buffer[self._buf_pos :] + data
        elif isinstance(data, memoryview):
            data = bytearray(data)
        self._buffer = data
        self._buf_pos = 0

    def unfeed(self, buf: VarByteType | None) -> int:
        "take from the buffer"
        if not self._buffer:
            return 0
        i = self._buf_pos
        n = min(len(buf) if buf is not None else 999, len(self._buffer) - i)
        if n == 0:
            return 0
        i_n = i + n
        if buf is not None:
            buf[:n] = self._buffer[i:i_n]
        self._buf_pos = i_n
        return n

    def has_extradata(self):
        "are there extra data in the buffer?"
        return self._buf_pos < len(self._buffer)

    def get_extradata(self):
        "return extra data, if any"
        return self._buffer[self._buf_pos :]

    def _read(self, n):
        # (int) -> bytearray
        i = self._buf_pos
        i_n = i + n
        if i_n > len(self._buffer):
            raise OutOfData

        ret = self._buffer[i:i_n]
        self._buf_pos = i + len(ret)
        return ret

    def _reserve(self, n):
        remain_bytes = len(self._buffer) - self._buf_pos - n

        # Fast path: buffer has n bytes already
        if remain_bytes >= 0:
            return

        raise OutOfData

    def _read_header(self):
        typ = _TYPE_IMMEDIATE
        n = 0
        obj = None
        self._reserve(1)
        b = self._buffer[self._buf_pos]
        self._buf_pos += 1
        if b & 0b10000000 == 0:  # x00-x7F
            obj = b
        elif b & 0b11100000 == 0b11100000:  # xE0-xFF
            obj = -1 - (b ^ 0xFF)
        elif b & 0b11100000 == 0b10100000:  # xA0-xBF
            n = b & 0b00011111
            typ = _TYPE_RAW
            obj = self._read(n)
        elif b & 0b11110000 == 0b10010000:  # x90-x9F
            n = b & 0b00001111
            typ = _TYPE_ARRAY
        elif b & 0b11110000 == 0b10000000:  # x80-x8F
            n = b & 0b00001111
            typ = _TYPE_MAP
        elif b == 0xC0:
            obj = None
        elif b == 0xC1:
            raise FormatError("unused code")
        elif b == 0xC2:
            obj = False
        elif b == 0xC3:
            obj = True
        elif b <= 0xC6:
            size, fmt, typ = _MSGPACK_HEADERS[b]
            self._reserve(size)
            if len(fmt) > 0:
                n = struct.unpack_from(fmt, self._buffer, self._buf_pos)[0]
            else:
                n = self._buffer[self._buf_pos]
            self._buf_pos += size
            obj = self._read(n)
        elif b <= 0xC9:
            size, fmt, typ = _MSGPACK_HEADERS[b]
            self._reserve(size)
            L, n = struct.unpack_from(fmt, self._buffer, self._buf_pos)
            self._buf_pos += size
            obj = self._read(L)
        elif b <= 0xD3:
            size, fmt = _MSGPACK_HEADERS[b]
            self._reserve(size)
            if len(fmt) > 0:
                obj = struct.unpack_from(fmt, self._buffer, self._buf_pos)[0]
            else:
                obj = self._buffer[self._buf_pos]
            self._buf_pos += size
        elif b <= 0xD8:
            size, fmt, typ = _MSGPACK_HEADERS[b]
            self._reserve(size + 1)
            n, obj = struct.unpack_from(fmt, self._buffer, self._buf_pos)
            self._buf_pos += size + 1
        elif b <= 0xDB:
            size, fmt, typ = _MSGPACK_HEADERS[b]
            self._reserve(size)
            if len(fmt) > 0:
                (n,) = struct.unpack_from(fmt, self._buffer, self._buf_pos)
            else:
                n = self._buffer[self._buf_pos]
            self._buf_pos += size
            obj = self._read(n)
        elif b <= 0xDD:
            size, fmt, typ = _MSGPACK_HEADERS[b]
            self._reserve(size)
            (n,) = struct.unpack_from(fmt, self._buffer, self._buf_pos)
            self._buf_pos += size
        else:  # if b <= 0xDF:  # can't be anything else
            size, fmt, typ = _MSGPACK_HEADERS[b]
            self._reserve(size)
            (n,) = struct.unpack_from(fmt, self._buffer, self._buf_pos)
            self._buf_pos += size
        return typ, n, obj

    def unpack(self):
        "extract one (top-level) item from the buffer"
        i = self._buf_pos
        try:
            res = self._unpack()
        except BaseException:
            self._buf_pos = i
            raise

        # Buffer management: chop off the part we've read
        self._buffer = self._buffer[self._buf_pos :]
        self._buf_pos = 0
        return res

    def _unpack(self):
        typ, n, obj = self._read_header()

        if typ == _TYPE_ARRAY:
            ret = []
            for _ in range(n):
                ret.append(self._unpack())
            # if self._list_hook is not None:
            # ret = self._list_hook(ret)
            return ret
        if typ == _TYPE_MAP:
            ret = attrdict() if self._use_attrdict else dict()
            for _ in range(n):
                key = self._unpack()
                if type(key) is str and hasattr(sys, "intern"):
                    key = sys.intern(key)
                elif isinstance(key, (bytearray, memoryview)):
                    key = bytes(key)
                ret[key] = self._unpack()
            # if self._object_hook is not None:
            # ret = self._object_hook(ret)
            return ret
        if typ == _TYPE_RAW:
            return byte2utf8(cast(bytes, obj))
        if typ == _TYPE_BIN:
            if self._min_memview_len < 0 and len(cast(bytes, obj)) < self._min_memview_len:
                obj = bytes(cast(bytes, obj))
            return obj
        if typ == _TYPE_EXT:
            return self._ext_hook(n, cast(bytes, obj))
        # assert typ == _TYPE_IMMEDIATE
        return obj

    def __aiter__(self):
        return self

    def __anext__(self):
        return self.unpack()

    def __iter__(self):
        return self

    def __next__(self):
        try:
            return self.unpack()
        except OutOfData:
            raise StopIteration  # noqa:B904,RUF100


class Packer:
    """
    Manager for buffered and streamed packing.
    """

    def __init__(
        self,
        # unicode_errors=None,
        default=None,
    ):
        self._buffer = BytesIO()
        # self._unicode_errors = unicode_errors or "strict"
        self._default = default

    def _pack(self, obj, default=None):
        # Warning, does not deal with recursive data structures
        # (except by running out of memory)
        list_types = (list, tuple)
        if default is None:
            default = self._default

        todo = [obj]

        # shorter bytecode
        def wp(*x):
            return self._buffer.write(struct.pack(*x))

        wb = self._buffer.write
        is_ = isinstance

        _ndefault = default
        while todo:
            _default, _ndefault = _ndefault, default
            obj = todo.pop()
            if obj is None:
                wb(b"\xc0")
                continue
            if isinstance(obj, bool):
                wb(b"\xc3" if obj else b"\xc2")
                continue
            if isinstance(obj, int):
                if obj >= 0:
                    if obj < 0x80:
                        wp("B", obj)
                        continue
                    if obj <= 0xFF:
                        wp("BB", 0xCC, obj)
                        continue
                    if obj <= 0xFFFF:
                        wp(">BH", 0xCD, obj)
                        continue
                    if obj <= 0xFFFFFFFF:
                        wp(">BI", 0xCE, obj)
                        continue
                    if obj <= 0xFFFFFFFFFFFFFFFF:
                        wp(">BQ", 0xCF, obj)
                        continue
                else:
                    if obj >= -0x20:
                        wp("b", obj)
                        continue
                    if obj >= -0x80:
                        wp(">Bb", 0xD0, obj)
                        continue
                    if obj >= -0x8000:
                        wp(">Bh", 0xD1, obj)
                        continue
                    if obj >= -0x80000000:
                        wp(">Bi", 0xD2, obj)
                        continue
                    if obj >= -0x8000000000000000:
                        wp(">Bq", 0xD3, obj)
                        continue
                if _default:
                    res = _default(obj)
                    if res is not None:
                        todo.append(res)
                        _ndefault = False
                        continue
                raise OverflowError("Integer value out of range")
            if is_(obj, (bytes, bytearray, memoryview)):
                # XXX we have a problem if memoryview.itemsize != 1
                n = len(obj)
                self._pack_bin_header(n)
                wb(obj)
                continue
            if is_(obj, str):
                obj = obj.encode("utf-8")  # , self._unicode_errors)
                n = len(obj)
                if n <= 0x1F:
                    wb(struct.pack("B", 0xA0 + n))
                elif n <= 0xFF:
                    wb(struct.pack(">BB", 0xD9, n))
                elif n <= 0xFFFF:
                    wb(struct.pack(">BH", 0xDA, n))
                else:
                    wb(struct.pack(">BI", 0xDB, n))
                wb(obj)
                continue
            if is_(obj, float):
                # if self._use_float:
                wp(">Bf", 0xCA, obj)
                # else:
                # wp(">Bd", 0xCB, obj)
                continue
            if is_(obj, ExtType):
                code = obj.code
                data = obj.data
                L = len(data)
                if L == 1:
                    wb(b"\xd4")
                elif L == 2:
                    wb(b"\xd5")
                elif L == 4:
                    wb(b"\xd6")
                elif L == 8:
                    wb(b"\xd7")
                elif L == 16:
                    wb(b"\xd8")
                elif L <= 0xFF:
                    wp(">BB", 0xC7, L)
                elif L <= 0xFFFF:
                    wp(">BH", 0xC8, L)
                else:
                    wp(">BI", 0xC9, L)
                wp("b", code)
                wb(data)
                continue
            if is_(obj, list_types):
                n = len(obj)
                if n <= 0x0F:
                    wb(struct.pack("B", 0x90 + n))
                elif n <= 0xFFFF:
                    wb(struct.pack(">BH", 0xDC, n))
                else:
                    wb(struct.pack(">BI", 0xDD, n))
                while n > 0:
                    n -= 1
                    todo.append(obj[n])
                continue
            if is_(obj, dict):
                n = len(obj)
                if n <= 0x0F:
                    wb(struct.pack("B", 0x80 + n))
                elif n <= 0xFFFF:
                    wb(struct.pack(">BH", 0xDE, n))
                else:
                    wb(struct.pack(">BI", 0xDF, n))
                for k, v in obj.items():
                    todo.append(v)
                    todo.append(k)
                continue
            if _default:
                res = _default(obj)
                if res is not None:
                    _ndefault = False
                    todo.append(res)
                    continue
            raise TypeError(f"Cannot serialize {obj!r}")

    def pack(self, obj):
        "Packs a single data item. Returns the bytes."
        try:
            self._pack(obj)
            return self._buffer.getvalue()
        finally:
            self._buffer = BytesIO()  # always reset

    def _pack_bin_header(self, n):
        wb = self._buffer.write
        if n <= 0xFF:
            return wb(struct.pack(">BB", 0xC4, n))
        if n <= 0xFFFF:
            return wb(struct.pack(">BH", 0xC5, n))
        return wb(struct.pack(">BI", 0xC6, n))


def packb(o, **kwargs):
    """
    Pack object `o` and return packed bytes

    See :class:`Packer` for options.
    """
    return Packer(**kwargs).pack(o)


def unpackb(packed, **kwargs):
    """
    Unpack an object from `packed`.

    Raises ``ExtraData`` when *packed* contains extra bytes.
    Raises ``OutOfData`` when *packed* is incomplete.
    Raises ``FormatError`` when *packed* is not valid msgpack.
    Other exceptions can be raised during unpacking.

    See :class:`Unpacker` for options.
    """
    unpacker = Unpacker(**kwargs)
    unpacker.feed(packed)
    try:
        res = unpacker.unpack()
        if unpacker.has_extradata():
            raise ExtraData
        return res
    except OutOfData:
        raise OutOfData("incomplete") from None
    raise RuntimeError("No way")
