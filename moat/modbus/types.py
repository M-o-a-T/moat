import struct
from typing import List

import anyio

try:
    from pymodbus.client.common import (
        ReadCoilsRequest,
        ReadCoilsResponse,
        ReadDiscreteInputsRequest,
        ReadDiscreteInputsResponse,
        ReadHoldingRegistersRequest,
        ReadHoldingRegistersResponse,
        ReadInputRegistersRequest,
        ReadInputRegistersResponse,
        WriteMultipleCoilsRequest,
        WriteMultipleCoilsResponse,
        WriteMultipleRegistersRequest,
        WriteMultipleRegistersResponse,
        WriteSingleCoilRequest,
        WriteSingleCoilResponse,
        WriteSingleRegisterRequest,
        WriteSingleRegisterResponse,
    )
except ImportError:
    from pymodbus.factory import (
        ReadDiscreteInputsRequest,
        ReadDiscreteInputsResponse,
        ReadCoilsRequest,
        ReadCoilsResponse,
        ReadHoldingRegistersRequest,
        ReadHoldingRegistersResponse,
        ReadInputRegistersRequest,
        ReadInputRegistersResponse,
        WriteSingleCoilRequest,
        WriteSingleCoilResponse,
        WriteMultipleCoilsRequest,
        WriteMultipleCoilsResponse,
        WriteSingleRegisterRequest,
        WriteSingleRegisterResponse,
        WriteMultipleRegistersRequest,
        WriteMultipleRegistersResponse,
    )

from pymodbus.datastore.store import BaseModbusDataBlock


def _singleton(x):
    x = x()
    return x


class BaseValue:
    """Base class for a single value.

    Do not instantiate directly.

    Set @idem if setting the item shall trigger iterators even if it
    doesn't change.
    """

    len = 0
    value = None
    gen = 0

    def __init__(self, value=None, idem=False):
        self.changed = anyio.Event()
        self.value = value
        self.idem = idem

        if value is not None:
            self.gen = 1
            self.changed = anyio.Event()

    def _decode(self, regs):
        raise NotImplementedError

    def _encode(self, value):
        raise NotImplementedError

    def decode(self, regs):
        val = self._decode(regs)
        if not self.idem and val == self.value:
            return
        self.value = self._decode(regs)
        self.changed.set()
        self.changed = anyio.Event()
        self.gen += 1

    def clear(self) -> None:
        """
        Clears the value.
        """
        if self.value is None:
            return
        self.value = None
        self.gen += 1
        self.changed.set()
        self.changed = anyio.Event()

    def encode(self):
        return self._encode(self.value)

    def __str__(self):
        return f"‹{self.value}›"

    def __repr__(self):
        return f"<{self.__class__.__name__}:{self.value}>"

    def __aiter__(self):
        return ValueIterator(self)


class _Signed:
    """A mix-in for signed integers."""

    def _decode(self, regs):
        res = super()._decode(regs)
        if res & 1 << (self.len * 16 - 1):
            res -= 1 << (self.len * 16)
        return res

    def _encode(self, value):
        if value < 0:
            value += 1 << (self.len * 16)
        return super()._encode(value)


class _Swapped:
    """A mix-in to byteswap the Modbus data."""

    def _decode(self, regs):
        regs.reverse()
        return super()._decode(regs)

    def _encode(self, value):
        regs = super()._encode(value)
        regs.reverse()
        return regs


class InaccessibleValue(BaseValue):  # duck-types but does NOT interit BaseValue
    """This register range must not be accessed.

    Use an instance of this type (with appropriate length)
    to force splitting a request into multiple parts.

    :param len: The length of the block that may not be accessed.
    """

    def __init__(self, len):
        self.len = len


class IntValue(BaseValue):
    """Simplest-possible value, one register."""

    len = 1

    def _decode(self, regs):
        return regs[0]

    def _encode(self, value):
        return (value,)


class LongValue(BaseValue):
    """32-bit integer, two registers, standard (big-endian) word order."""

    len = 2

    def _decode(self, regs):
        return (regs[0] << 16) | regs[1]

    def _encode(self, value):
        return (value >> 16, value & 0xFFFF)


class QuadValue(BaseValue):
    """64-bit integer, four registers, standard (big-endian) word order.

    This is a BaseValue instance.
    """

    len = 4

    def _decode(self, regs):
        return (((((regs[0] << 16) + regs[1]) << 16) + regs[2]) << 16) + regs[3]

    def _encode(self, value):
        return (
            (value >> 48) & 0xFFFF,
            (value >> 32) & 0xFFFF,
            (value >> 16) & 0xFFFF,
            value & 0xFFFF,
        )


class FloatValue(BaseValue):
    """network-ordered floating point."""

    len = 2

    def _decode(self, regs):
        return struct.unpack(">f", struct.pack(">2H", *regs))[0]

    def _encode(self, value):
        return struct.unpack(">2H", struct.pack(">f", value))


class DoubleValue(BaseValue):
    """network-ordered accurate floating point."""

    len = 4

    def _decode(self, regs):
        return struct.unpack(">d", struct.pack(">4H", *regs))[0]

    def _encode(self, value):
        return struct.unpack(">4H", struct.pack(">d", value))


class SwappedLongValue(_Swapped, LongValue):
    """32-bit integer, two registers, little-endian word order."""

    pass


class SwappedQuadValue(_Swapped, QuadValue):
    """64-bit integer, four registers, little-endian word order."""

    pass


class SignedIntValue(_Signed, IntValue):
    """one register, signed."""

    pass


class SignedLongValue(_Signed, LongValue):
    """two registers, signed."""

    pass


class SwappedSignedLongValue(_Signed, _Swapped, BaseValue):
    """two registers, signed, swapped."""

    pass


SignedSwappedLongValue = SwappedSignedLongValue


class SignedQuadValue(_Signed, QuadValue):
    """four registers, signed."""

    pass


class SwappedSignedQuadValue(_Signed, _Swapped, QuadValue):
    """four registers, signed, swapped."""

    pass


SignedSwappedQuadValue = SwappedSignedQuadValue


class SwappedFloatValue(_Swapped, FloatValue):
    """broken-ordered floating point."""

    pass


class SwappedDoubleValue(_Swapped, DoubleValue):
    """broken-ordered accurate floating point."""

    pass


class TypeCodec:
    """Base class for access types. Do not instantiate."""

    typ = None
    acc = None

    def __repr__(self):
        return self.__class__.__name__

    def __eq__(self, typ):
        if isinstance(typ, TypeCodec):
            typ = typ.typ
        return self.typ == typ

    def __hash__(self):
        return self.typ


@_singleton
class Coils(TypeCodec):
    """Modbus 'coils' data.
    This is a TypeCodec.
    """

    typ = 0
    key = "c"
    encoder = ReadCoilsRequest
    decoder = ReadCoilsResponse
    encoder_s = WriteSingleCoilRequest
    decoder_s = WriteSingleCoilResponse
    encoder_m = WriteMultipleCoilsRequest
    decoder_m = WriteMultipleCoilsResponse


@_singleton
class DiscreteInputs(TypeCodec):
    """Modbus 'discrete input' data.
    This is a TypeCodec.
    """

    typ = 1
    key = "d"
    encoder = ReadDiscreteInputsRequest
    decoder = ReadDiscreteInputsResponse


@_singleton
class HoldingRegisters(TypeCodec):
    """Modbus 'holding register' data.
    This is a TypeCodec.
    """

    typ = 2
    key = "h"
    encoder = ReadHoldingRegistersRequest
    decoder = ReadHoldingRegistersResponse
    encoder_s = WriteSingleRegisterRequest
    decoder_s = WriteSingleRegisterResponse
    encoder_m = WriteMultipleRegistersRequest
    decoder_m = WriteMultipleRegistersResponse


@_singleton
class InputRegisters(TypeCodec):
    """Modbus 'input register' data.
    This is a TypeCodec.
    """

    typ = 3
    key = "i"
    encoder = ReadInputRegistersRequest
    decoder = ReadInputRegistersResponse


class DataBlock(dict, BaseModbusDataBlock):
    """Your basic sparse data block.

    The @changed attribute is an event that triggers when a write request
    succeeds.
    """

    def __init__(self, max_len=30):
        super().__init__()
        self.max_len = max_len
        self.changed = anyio.Event()

    def default(self, count, value=False):
        raise NotImplementedError

    def reset(self):
        for val in self.values():
            val.value = None

    def add(self, offset: int, val: BaseValue):
        if offset in self:
            raise ValueError("Already known", i)
        for n in range(1, 8):
            try:
                if self[offset - n].len > n:
                    raise ValueError(f"Overlap with {self[offset-n]} @{offset-n}")
                break
            except KeyError:
                pass
        for n in range(1, val.len):
            try:
                if offset + n in self:
                    raise ValueError(f"Overlap with {self[offset+n]} @{offset+n}")
                break
            except KeyError:
                pass
        self[offset] = val

    def validate(self, address: int, count: int = 1):
        if not count:
            return False
        while count:
            try:
                val = self[address]
                if val.len <= 0:
                    raise RuntimeError("invalid")
            except (KeyError, RuntimeError):
                return False
            address += val.len
            count -= val.len
        return True

    def ranges(self):
        """Iterate over to-be-retrieved range(s)."""
        start, cur = None, None
        for offset, val in sorted(self.items()):
            if isinstance(val, InaccessibleValue):
                if start is not None:
                    yield (start, cur - start)
                    start = None
            elif start is None:
                start = offset
                cur = start + val.len
            elif cur == offset and (cur + val.len - start) <= self.max_len:
                cur += val.len
            else:
                yield (start, cur - start)
                start = offset
                cur = start + val.len

        if cur is not None:
            yield (start, cur - start)

    def getValues(self, address: int, count=1):
        """Get the array of Modbus values for the @address:+@count range"""
        res = []
        while count > 0:
            try:
                val = self[address]
            except KeyError:
                res.append(0)
                address += 1
                count -= 1
            else:
                res.extend(val.encode())
                address += val.len
                count -= val.len
        if count < 0:
            # well, this shouldn't happen but …
            res = res[:count]
        return res

    def setValues(self, address: int, values: List[int]):
        """Set the variables starting at @address to @values"""
        while values:
            try:
                val = self[address]
            except KeyError:
                address += 1
                values.pop(0)
            else:
                val.decode(values[: val.len])
                address += val.len
                values = values[val.len :]

        self.changed.set()
        self.changed = anyio.Event()

    def delete(self, address, count=1):
        while count:
            self.pop(address, None)
            address += 1
            count -= 1


class ValueIterator:
    """
    Helper class for iterating over `BaseValue` changes.

    Posts a notification when values get skipped.
    """

    def __init__(self, val):
        self.val = val
        self.gen = max(0, val.gen - 1)

    async def __anext__(self):
        """
        Iterate over values / value changes.

        If the value is initially unknown, wait.
        if it's been cleared, raises `StopAsyncIteration`.
        """
        val = self.val
        if val.gen > 0 and val.value is None:
            raise StopAsyncIteration
        if self.gen == val.gen:
            await val.changed.wait()
        if val.value is None:
            raise StopAsyncIteration
        if self.gen + 1 != val.gen:
            logger.notice("%r: skipped %d", val.gen - self.gen - 1)
        self.gen = val.gen
        return val.value
