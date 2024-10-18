"""
An overly-simple CBOR packer/unpacker.
"""

from __future__ import annotations

import struct
from io import BytesIO
import datetime as dt

import datetime as dt
from ipaddress import IPv4Address, IPv4Network, IPv6Address, IPv6Network


from .impl import NotGiven
from .proxy import Proxy, obj2name, name2obj
from .path import Path

# Typing
from typing import TYPE_CHECKING  # isort:skip

if TYPE_CHECKING:
    from typing import Any


def const(x):
    "µPy compatibility"
    return x


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


def _dumps_bignum_to_bytearray(val):
    return val.to_bytes((val.bit_length() + 7) // 8, "big")


class ExtraData(ValueError):
    "buffer contains data beyond end of encoded object"

    def __init__(self, unpacked, extra):
        self.unpacked = unpacked
        self.extra = extra

    def __str__(self):
        return "unpack(b) received extra data."


class OutOfData(EOFError):
    "bytes missing"


class Packer:
    "Basic CBOR packer"

    def __init__(self):
        self._buffer = BytesIO()
        # self._unicode_errors = unicode_errors or "strict"

    def _int(self, val):
        "return bytes representing int val in CBOR"
        if val < 0:
            val = -1 - val
            return self._encode_type_num(CBOR_NEGINT, val)
        return self._encode_type_num(CBOR_UINT, val)

    def _bignum_to_bytearray(self, val):
        out = []
        while val > 0:
            out.insert(0, val & 0x0FF)
            val = val >> 8
        return bytes(out)

    def _float(self, val):
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

    def _encode_type_num(self, cbor_type, val) -> None:
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
        if val <= (0x07FFFFFFFFFFFFFFF if cbor_type == CBOR_NEGINT else 0x0FFFFFFFFFFFFFFFF):
            return w(struct.pack("!BQ", cbor_type | CBOR_UINT64_FOLLOWS, val))

        # too large: write a bignum
        if cbor_type == CBOR_UINT:
            w(_CBOR_TAG_BIGNUM_BYTES)
        elif cbor_type == CBOR_NEGINT:
            w(_CBOR_TAG_NEGBIGNUM_BYTES)
        else:
            raise ValueError("value too big: " + repr(val))
        outb = _dumps_bignum_to_bytearray(val)
        self._encode_type_num(CBOR_BYTES, len(outb))
        w(self._bignum_to_bytearray(val))
        return None

    def _string(self, val):
        if isinstance(val, str):
            val = val.encode("utf8")
            self._encode_type_num(CBOR_TEXT, len(val))
        else:
            self._encode_type_num(CBOR_BYTES, len(val))
        self._w(val)

    def _array(self, arr):
        try:
            self._encode_type_num(CBOR_ARRAY, len(arr))
        except TypeError:
            self._encode_type_num(CBOR_ARRAY, None)
            for x in arr:
                self._any(x)
            self._w(struct.pack("B", CBOR_BREAK))
        else:
            for x in arr:
                self._any(x)

    def _dict(self, d):
        self._encode_type_num(CBOR_MAP, len(d))
        for k, v in d.items():
            self._any(k)
            self._any(v)

    def _bool(self, b):
        if b:
            self._w(struct.pack("B", CBOR_TRUE))
        self._w(struct.pack("B", CBOR_FALSE))

    def _tag(self, t, val=NotGiven):
        if val is NotGiven:
            t,val = t.tag, t.value
        self._encode_type_num(CBOR_TAG, t)
        self._any(val)

    def _w(self, d):
        self._buffer.write(d)

    def _any(self, ob):
        w = self._w
        if ob is None:
            w(struct.pack("B", CBOR_NULL))
        elif ob is NotGiven:
            w(struct.pack("B", CBOR_UNDEFINED))
        elif isinstance(ob, bool):
            self._bool(ob)
        elif isinstance(ob, (str, bytes)):
            self._string(ob)
        elif isinstance(ob, (list, tuple)):
            self._array(ob)
        # TODO: accept other enumerables and emit a variable length array
        elif isinstance(ob, dict):
            self._dict(ob)
        elif isinstance(ob, float):
            self._float(ob)
        elif isinstance(ob, int):
            self._int(ob)
        elif isinstance(ob, Tag):
            self._tag(ob)
        elif type(ob) in encoders:
            enc = encoders[type(ob)]
            self._tag(enc(ob))
        else:
            try:
                name = obj2name(ob)
            except KeyError:
                try:
                    name = obj2name(type(ob))
                except KeyError:
                    raise ValueError(f"not proxied: {ob !r}")
                else:
                    p = ob.__getstate__()
                    if not isinstance(p, (list, tuple)):
                        p = (p,)
                    self._tag(27, (Tag(203, name),) + p)
            else:
                self._tag(203, name)

    def packb(self, obj):
        "pack @obj, return the resulting bytes"
        if self._buffer.getvalue():
            raise RuntimeError("Writer busy")
        try:
            self._any(obj)
            return self._buffer.getvalue()
        finally:
            self._buffer = BytesIO()  # always reset


class Tag:
    "a random CBOR tag"

    def __init__(self, tag=None, value=None):
        self.tag = tag
        self.value = value

    def __repr__(self):
        return f"Tag({self.tag !r}, {self.value !r})"

    def __eq__(self, other):
        if not isinstance(other, Tag):
            return False
        return self.tag == other.tag and self.value == other.value

    def __hash__(self):
        return hash(self.tag) ^ hash(self.value)


class Unpacker:
    "Basic CBOR unpacker"

    _stream = None
    _buff_i = 0
    _rsz = 64

    _MAX_DEPTH = 100

    def __init__(self, stream=None):
        self._stream = stream
        self._buffer = bytearray()

    async def _tag_aux(self, tb):
        tag = tb & CBOR_TYPE_MASK
        tag_aux = tb & CBOR_INFO_BITS
        if tag_aux <= 23:
            aux = tag_aux
        elif tag_aux == CBOR_UINT8_FOLLOWS:
            data = await self._read(1)
            aux = struct.unpack_from("!B", data, 0)[0]
        elif tag_aux == CBOR_UINT16_FOLLOWS:
            data = await self._read(2)
            aux = struct.unpack_from("!H", data, 0)[0]
        elif tag_aux == CBOR_UINT32_FOLLOWS:
            data = await self._read(4)
            aux = struct.unpack_from("!I", data, 0)[0]
        elif tag_aux == CBOR_UINT64_FOLLOWS:
            data = await self._read(8)
            aux = struct.unpack_from("!Q", data, 0)[0]
        else:
            assert tag_aux == CBOR_VAR_FOLLOWS, f"bogus tag {tb:02x}"
            aux = None

        return tag, aux

    async def _read(self, n):
        # (int) -> bytearray
        await self._reserve(n)
        i = self._buff_i
        ret = self._buffer[i : i + n]
        self._buff_i = i + len(ret)
        return ret

    async def _read_byte(self):
        return (await self._read(1))[0]

    async def _reserve(self, n):
        nb = self._buff_i + n - len(self._buffer)

        # Fast path: buffer has n bytes already
        if nb <= 0:
            return

        if not self._stream:
            raise OutOfData

        # Read from file
        while nb > 0:
            to_read_bytes = max(self._rsz, nb)
            read_data = await self._stream.recv(to_read_bytes)
            if not read_data:
                break
            self._buffer += read_data
            nb -= len(read_data)

        if len(self._buffer) < n + self._buff_i:
            self._buff_i = 0  # rollback
            raise OutOfData

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
            raise StopIteration from None
        #       except BaseException as err:
        #           raise RuntimeError(err)
        else:
            raise RuntimeError("Needs async")

    async def _var_array(self):
        ob = []
        tb = await self._read_byte()
        while tb != CBOR_BREAK:
            subob = await self._tb(tb)
            ob.append(subob)
            tb = await self._read_byte()
        return ob

    async def _var_map(self):
        ob = {}
        tb = self._read_byte()
        while tb != CBOR_BREAK:
            subk = await self._tb(tb)
            subv = await self._any()
            ob[subk] = subv
            tb = self._read_byte()
        return ob

    async def _array(self, aux):
        ob = []
        for _ in range(aux):
            subob = await self._any()
            ob.append(subob)
        return ob

    async def _map(self, aux):
        ob = {}
        for _ in range(aux):
            subk = await self._any()
            subv = await self._any()
            ob[subk] = subv
        return ob

    async def unpack(self) -> Any:
        "unpack my buffer into an object"
        res = await self._any()
        # Buffer management: chop off the part we've read
        self._buffer = self._buffer[self._buff_i :]
        self._buff_i = 0
        return res

    def _got_extradata(self):
        return self._buff_i < len(self._buffer)

    def _get_extradata(self):
        return self._buffer[self._buff_i :]

    def unpackb(self, packed) -> Any:
        "unpack"
        self.feed(packed)
        try:
            upack = self.unpack()
            upack.send(None)
        except StopIteration as s:
            if self._got_extradata():
                raise ExtraData(s.value, bytes(self._get_extradata())) from None
            return s.value
        except OutOfData:
            raise ValueError("incomplete") from None
        raise RuntimeError("No way")

    def feed(self, data: bytes):
        "set the decode buffer"
        assert self._stream is None
        self._buffer = memoryview(data)
        self._buff_i = 0

    async def _any(self):
        #       if depth > _MAX_DEPTH:
        #           raise RuntimeError("load recursion limit")

        tb = await self._read_byte()
        return await self._tb(tb)

    async def _tb(self, tb):
        # Some special cases of CBOR_7 best handled by special struct.unpack logic here
        if tb == CBOR_FLOAT16:
            data = await self._read(2)
            pf = struct.unpack_from("!e", data, 0)
            return pf[0]
        elif tb == CBOR_FLOAT32:
            data = await self._read(4)
            pf = struct.unpack_from("!f", data, 0)
            return pf[0]
        elif tb == CBOR_FLOAT64:
            data = await self._read(8)
            pf = struct.unpack_from("!d", data, 0)
            return pf[0]

        tag, aux = await self._tag_aux(tb)

        if tag == CBOR_UINT:
            return aux
        elif tag == CBOR_NEGINT:
            return -1 - aux
        elif tag == CBOR_BYTES:
            return await self._bytes(aux)
        elif tag == CBOR_TEXT:
            return str(await self._bytes(aux, btag=CBOR_TEXT), "utf8")
        elif tag == CBOR_ARRAY:
            if aux is None:
                return await self._var_array()
            return await self._array(aux)
        elif tag == CBOR_MAP:
            if aux is None:
                return await self._var_map()
            return await self._map(aux)
        elif tag == CBOR_TAG:
            ob = await self._any()
            # attempt to interpet the tag and the value into a Python object.
            try:
                dec = decoders[aux]
            except KeyError:
                return Tag(aux, ob)
            else:
                return dec(ob)
        else:
            assert tag == CBOR_7
            if tb == CBOR_TRUE:
                return True
            if tb == CBOR_FALSE:
                return False
            if tb == CBOR_NULL:
                return None
            if tb == CBOR_UNDEFINED:
                return NotGiven
            raise ValueError(f"unknown cbor tag 7 byte: {tb:02x}")

    async def _bytes(self, aux, btag=CBOR_BYTES):
        # TODO: limit to some maximum number of chunks and some maximum total bytes
        if aux is not None:
            # simple case
            ob = await self._read(aux)
            return ob
        # read chunks of bytes
        chunklist = []
        while True:
            tb = await self._read_byte()
            if tb == CBOR_BREAK:
                break
            tag, aux = await self._tag_aux(tb)
            if tag != btag:
                raise ValueError("var length with unexpected component")
            ob = await self._read(aux)
            chunklist.append(ob)
        return b"".join(chunklist)


## built-in codecs

def _enc_datetime_ts(value):
    # Semantic tag 1
    if not value.tzinfo:
        raise ValueError(f"naive datetime {value!r}")

    from calendar import timegm

    if value.microsecond:
        timestamp = timegm(value.utctimetuple()) + value.microsecond / 1000000
    else:
        timestamp: float = timegm(value.utctimetuple())

    return Tag(1, timestamp)

def _enc_datetime_str(value):
    # Semantic tag 0
    if not value.tzinfo:
        raise ValueError(f"naive datetime {value!r}")

    datestring = value.isoformat().replace("+00:00", "Z")
    return Tag(0, datestring)


def _dec_datetime_string(value) -> datetime:
    # Semantic tag 0
    match = timestamp_re.match(value)
    if match:
        (
            year,
            month,
            day,
            hour,
            minute,
            second,
            secfrac,
            offset_sign,
            offset_h,
            offset_m,
        ) = match.groups()
        if secfrac is None:
            microsecond = 0
        else:
            microsecond = int(f"{secfrac:<06}")

        if offset_h:
            if offset_sign == "-":
                sign = -1
            else:
                sign = 1
            hours = int(offset_h) * sign
            minutes = int(offset_m) * sign
            tz = timezone(timedelta(hours=hours, minutes=minutes))
        else:
            tz = timezone.utc

        return dt.datetime(
                int(year),
                int(month),
                int(day),
                int(hour),
                int(minute),
                int(second),
                microsecond,
                tz,
            )
    else:
        raise ValueError(f"invalid datetime string: {value!r}")

def _dec_type(val):
    if not isinstance(val[0], type):
        raise ValueError(f"invalid type: {val!r}")
    return val[0](*(val[1] if len(val) > 1 else ()),**(val[2] if len(val) > 2 else ()))

def _dec_proxy(val):
    try:
        if isinstance(val,(str,int)):
            return name2obj(val)
        elif len(val) != 2:  # cop-out
            return Tag(27,val)
        else:
            return name2obj(*val)
    except KeyError:
        return Proxy(val)

def _dec_obj(val):
    pk = object.__new__(val[0])
    try:
        pk.__setstate__(*val[1:])
    except AttributeError:
        pk.__dict__.update(val[1])
    return pk

# bignums are handled separately
encoders = {
    dt.datetime: _enc_datetime_ts, # _enc_dattime_str
    IPv4Address: lambda adr: Tag(260, adr.packed),
    IPv6Address: lambda adr: Tag(260, adr.packed),
    IPv4Network: lambda adr: Tag(261, {adr.network_address.packed: adr.prefixlen}),
    IPv6Network: lambda adr: Tag(261, {adr.network_address.packed: adr.prefixlen}),
    Path: lambda val: Tag(202, val._data),
    Proxy: lambda val: Tag(203, {adr.network_address.packed: adr.prefixlen}),
}

decoders = {
    0: _dec_datetime_string,
    1: lambda val: datetime.fromtimestamp(val, timezone.utc),
    2: lambda val: int.from_bytes(val, "big"),
    3: lambda val: -1 - int.from_bytes(val, "big"),
    27: _dec_obj,
    202: lambda val: Path(*val),
    203: _dec_proxy,
    55799: lambda val: val,
}


def packb(o, **kwargs):
    """
    Pack object `o` and return packed bytes

    See :class:`Packer` for options.
    """
    return Packer(**kwargs).packb(o)


def unpackb(packed, **kwargs):
    """
    Unpack an object from `packed`.

    See :class:`Unpacker` for options.
    """
    unpacker = Unpacker(None, **kwargs)
    return unpacker.unpackb(packed)
