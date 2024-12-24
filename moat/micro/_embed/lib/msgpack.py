"""
This is a micropython-asyncio-compatible MsgPack implementation.
It does not support
* a "default" fallback encoder
* encoding binary data to strings (which is legacy nonsense anyway)
* auto-encoding datetime to the timestamp extension
* the object_pairs hook

The encoder is synchronous and returns bytes.
The decoder is async and yields messages.
You can also decode single messages synchronously.

The decoder returns binary data as memoryviews if they're larger
than the threshold (default -1: always copy). Extension objects always
get a memoryview and must decode or copy it.
"""
# cloned from https://github.com/msgpack/msgpack-python

# Parts of this have been modified to be compatble with micropython.
from __future__ import annotations

import struct
import sys
from io import BytesIO

from micropython import const

from moat.util import attrdict

# ruff:noqa:TRY200


class UnpackException(Exception):
    "superclass, not raised"


class OutOfData(UnpackException):
    "missing data in buffer"


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


_TYPE_IMMEDIATE = const(0)
_TYPE_ARRAY = const(1)
_TYPE_MAP = const(2)
_TYPE_RAW = const(3)
_TYPE_BIN = const(4)
_TYPE_EXT = const(5)

DEFAULT_RECURSE_LIMIT = 20


_NO_FORMAT_USED = ""
_MSGPACK_HEADERS = {
    0xC4: (1, _NO_FORMAT_USED, _TYPE_BIN),
    0xC5: (2, ">H", _TYPE_BIN),
    0xC6: (4, ">I", _TYPE_BIN),
    0xC7: (2, "Bb", _TYPE_EXT),
    0xC8: (3, ">Hb", _TYPE_EXT),
    0xC9: (5, ">Ib", _TYPE_EXT),
    0xCA: (4, ">f"),
    0xCB: (8, ">d"),
    0xCC: (1, _NO_FORMAT_USED),
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
    0xD9: (1, _NO_FORMAT_USED, _TYPE_RAW),
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
        stream=None,
        read_size=64,
        # use_list=True,
        # object_hook=None,
        # list_hook=None,
        # unicode_errors="strict",
        ext_hook=ExtType,
        min_memview_len=-1,
    ):
        self._stream = stream

        #: array of bytes fed.
        self._buffer = bytearray()
        #: Which position we currently reads
        self._buff_i = 0

        self._read_size = read_size
        # self._unicode_errors = unicode_errors
        # self._use_list = use_list
        # self._list_hook = list_hook
        # self._object_hook = object_hook
        self._ext_hook = ext_hook
        self._min_memview_len = min_memview_len

    def feed(self, data):
        "set the buffer"
        assert self._stream is None
        self._buffer = memoryview(data)
        self._buff_i = 0

    def has_extradata(self):
        "are there extra data in the buffer?"
        return self._buff_i < len(self._buffer)

    def get_extradata(self):
        "return extra data, if any"
        return self._buffer[self._buff_i :]

    # async def read_bytes(self, n):
    # ret = await self._read(n, raise_outofdata=False)
    # self._consume()
    # return ret

    async def _read(self, n, raise_outofdata=True):
        # (int) -> bytearray
        await self._reserve(n, raise_outofdata=raise_outofdata)
        i = self._buff_i
        ret = self._buffer[i : i + n]
        self._buff_i = i + len(ret)
        return ret

    async def _reserve(self, n, raise_outofdata=True):
        remain_bytes = len(self._buffer) - self._buff_i - n

        # Fast path: buffer has n bytes already
        if remain_bytes >= 0:
            return

        if not self._stream:
            raise OutOfData

        # Read from file
        remain_bytes = -remain_bytes
        while remain_bytes > 0:
            to_read_bytes = max(self._read_size, remain_bytes)
            # TODO simplify, read into existing buffer
            b = bytearray(to_read_bytes)
            read_data = await self._stream.rd(b)
            if not read_data:
                break
            self._buffer += b[:read_data]
            remain_bytes -= read_data

        if len(self._buffer) < n + self._buff_i and raise_outofdata:
            self._buff_i = 0  # rollback
            raise OutOfData

    async def _read_header(self):
        typ = _TYPE_IMMEDIATE
        n = 0
        obj = None
        await self._reserve(1)
        b = self._buffer[self._buff_i]
        self._buff_i += 1
        if b & 0b10000000 == 0:  # x00-x7F
            obj = b
        elif b & 0b11100000 == 0b11100000:  # xE0-xFF
            obj = -1 - (b ^ 0xFF)
        elif b & 0b11100000 == 0b10100000:  # xA0-xBF
            n = b & 0b00011111
            typ = _TYPE_RAW
            obj = await self._read(n)
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
            await self._reserve(size)
            if len(fmt) > 0:
                n = struct.unpack_from(fmt, self._buffer, self._buff_i)[0]
            else:
                n = self._buffer[self._buff_i]
            self._buff_i += size
            obj = await self._read(n)
        elif b <= 0xC9:
            size, fmt, typ = _MSGPACK_HEADERS[b]
            await self._reserve(size)
            L, n = struct.unpack_from(fmt, self._buffer, self._buff_i)
            self._buff_i += size
            obj = await self._read(L)
        elif b <= 0xD3:
            size, fmt = _MSGPACK_HEADERS[b]
            await self._reserve(size)
            if len(fmt) > 0:
                obj = struct.unpack_from(fmt, self._buffer, self._buff_i)[0]
            else:
                obj = self._buffer[self._buff_i]
            self._buff_i += size
        elif b <= 0xD8:
            size, fmt, typ = _MSGPACK_HEADERS[b]
            await self._reserve(size + 1)
            n, obj = struct.unpack_from(fmt, self._buffer, self._buff_i)
            self._buff_i += size + 1
        elif b <= 0xDB:
            size, fmt, typ = _MSGPACK_HEADERS[b]
            await self._reserve(size)
            if len(fmt) > 0:
                (n,) = struct.unpack_from(fmt, self._buffer, self._buff_i)
            else:
                n = self._buffer[self._buff_i]
            self._buff_i += size
            obj = await self._read(n)
        elif b <= 0xDD:
            size, fmt, typ = _MSGPACK_HEADERS[b]
            await self._reserve(size)
            (n,) = struct.unpack_from(fmt, self._buffer, self._buff_i)
            self._buff_i += size
        else:  # if b <= 0xDF:  # can't be anything else
            size, fmt, typ = _MSGPACK_HEADERS[b]
            await self._reserve(size)
            (n,) = struct.unpack_from(fmt, self._buffer, self._buff_i)
            self._buff_i += size
        return typ, n, obj

    async def unpack(self):
        "extract one (top-level) item from the buffer"
        res = await self._unpack()
        # Buffer management: chop off the part we've read
        self._buffer = self._buffer[self._buff_i :]
        self._buff_i = 0
        return res

    async def _unpack(self):
        typ, n, obj = await self._read_header()

        if typ == _TYPE_ARRAY:
            ret = []
            for _ in range(n):
                ret.append(await self.unpack())
            # if self._list_hook is not None:
            # ret = self._list_hook(ret)
            # TODO is the interaction between `list_hook` and `use_list` ok?
            return ret  # if self._use_list else tuple(ret)
        if typ == _TYPE_MAP:
            ret = attrdict()
            for _ in range(n):
                key = await self.unpack()
                if type(key) is str and hasattr(sys, "intern"):
                    key = sys.intern(key)
                ret[key] = await self.unpack()
            # if self._object_hook is not None:
            # ret = self._object_hook(ret)
            return ret
        if typ == _TYPE_RAW:
            if isinstance(obj, memoryview):  # sigh
                obj = bytearray(obj)
            return obj.decode("utf_8")  # , self._unicode_errors)
        if typ == _TYPE_BIN:
            if self._min_memview_len < 0 and len(obj) < self._min_memview_len:
                obj = bytearray(obj)
            return obj
        if typ == _TYPE_EXT:
            return self._ext_hook(n, obj)
        # assert typ == _TYPE_IMMEDIATE
        return obj

    def __aiter__(self):
        return self

    def __anext__(self):
        return self.unpack()

    def __iter__(self):
        return self

    def __next__(self):
        g = self.unpack()
        try:
            g.send(None)
        except StopIteration as exc:
            return exc.value
        except OutOfData:
            raise StopIteration
        except BaseException as err:
            raise RuntimeError(err)
        else:
            raise RuntimeError("Needs async")


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


# def pack(o, stream, **kwargs):
#    """
#    Pack object `o` and write it to `stream`
#
#    See :class:`Packer` for options.
#    """
#    packer = Packer(**kwargs)
#    stream.write(packer.packb(o))


def packb(o, **kwargs):
    """
    Pack object `o` and return packed bytes

    See :class:`Packer` for options.
    """
    return Packer(**kwargs).pack(o)


# def unpack(stream, **kwargs):
#    """
#    Unpack an object from `stream`.
#
#    Raises `ExtraData` when `stream` contains extra bytes.
#    See :class:`Unpacker` for options.
#    """
#    data = stream.read()
#    return unpackb(data, **kwargs)


def unpackb(packed, **kwargs):
    """
    Unpack an object from `packed`.

    Raises ``ExtraData`` when *packed* contains extra bytes.
    Raises ``ValueError`` when *packed* is incomplete.
    Raises ``FormatError`` when *packed* is not valid msgpack.
    Other exceptions can be raised during unpacking.

    See :class:`Unpacker` for options.
    """
    unpacker = Unpacker(None, **kwargs)
    unpacker.feed(packed)
    try:
        next(unpacker.unpack())
    except StopIteration as s:
        if unpacker.has_extradata():
            raise ExtraData(s.value, bytes(unpacker.get_extradata()))
        return s.value
    except OutOfData:
        raise ValueError("incomplete")
    raise RuntimeError("No way")
