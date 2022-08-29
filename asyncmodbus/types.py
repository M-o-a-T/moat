import struct

from pymodbus.client.common import (
    ReadDiscreteInputsRequest,
    ReadDiscreteInputsResponse,
    ReadCoilsRequest,
    ReadCoilsResponse,
    ReadHoldingRegistersRequest,
    ReadHoldingRegistersResponse,
    ReadInputRegistersRequest,
    ReadInputRegistersResponse,
)

def singleton(x):
    x = x()
    return x


class BaseValue:
    """Base class for reading a single value.

    Do not instantiate.
    """

    len = 0
    value = None

    def _decode(self, regs):
        raise NotImplementedError

    def _encode(self, value):
        raise NotImplementedError

    def decode(self, regs):
        self.value = self._decode(regs)

    def encode(self):
        return self._encode(self.value)

    def __str__(self):
        return f'‹{self.value}›'

    def __repr__(self):
        return f'<{self.__class__.__name__}:{self.value}>'


class _Signed:
    """A mix-in for signed integers."""
    def _decode(self, regs):
        res = super()._decode(regs)
        if res & 1<<(self.len*16-1):
            res -= 1<<(self.len*16)
        return res

    def _encode(self, value):
        if value < 0:
            value += 1<<(self.len*16)
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
    """Simplest-possible value, one register.
    """

    len = 1

    def _decode(self, regs):
        return regs[0]

    def _encode(self, value):
        return (value,)


class LongValue(BaseValue):
    """32-bit integer, two registers, standard (big-endian) word order.
    """

    len = 2

    def _decode(self, regs):
        return regs[0] * 65536 + regs[1]

    def _encode(self, value):
        return (value & 0xFFFF, value >> 16)

class SwappedLongValue(_Swapped, LongValue):
    """32-bit integer, two registers, little-endian word order.

    This is a BaseValue instance.
    """
    pass

class QuadValue(BaseValue):
    """64-bit integer, four registers, standard (big-endian) word order.

    This is a BaseValue instance.
    """

    len = 4

    def _decode(self, regs):
        return (((((regs[0] << 16) + regs[1]) << 16) + regs[2]) << 16) + regs[3]

    def _encode(self, value):
        return (
            value & 0xFFFF,
            (value >> 16) & 0xFFFF,
            (value >> 32) & 0xFFFF,
            (value >> 48) & 0xFFFF,
        )


class SwappedQuadValue(_Swapped, QuadValue):
    """64-bit integer, four registers, little-endian word order.
    """
    pass


class SignedIntValue(_Signed, IntValue):
    """one register, signed.
    """
    pass

class SignedLongValue(_Signed, LongValue):
    """two registers, signed.
    """
    pass


class SwappedSignedLongValue(_Signed, _Swapped, BaseValue):
    """two registers, signed, swapped.
    """
    pass

SignedSwappedLongValue = SwappedSignedLongValue


class SignedQuadValue(_Signed, QuadValue):
    """four registers, signed.
    """
    pass


class SwappedSignedQuadValue(_Signed, _Swapped, QuadValue):
    """four registers, signed, swapped.
    """
    pass

SignedSwappedQuadValue = SwappedSignedQuadValue


class FloatValue(BaseValue):
    """network-ordered floating point.
    """

    len = 2

    def _decode(self, regs):
        return struct.unpack(">f", struct.pack(">2H", *regs))[0]

    def _encode(self, value):
        return struct.pack(">f", value)


class SwappedFloatValue(_Swapped, FloatValue):
    """network-ordered floating point.
    """
    pass


class DoubleValue(BaseValue):
    """network-ordered accurate floating point.
    """

    len = 4

    def _decode(self, regs):
        return struct.unpack(">d", struct.pack(">4H", *regs))[0]

    def _encode(self, value):
        return struct.pack(">d", value)


class SwappedDoubleValue(_Swapped, DoubleValue):
    """network-ordered accurate floating point.
    """
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


@singleton
class Coils(TypeCodec):
    """Modbus 'coils' data.
    This is a TypeCodec.
    """

    typ = 0
    encoder = ReadCoilsRequest
    decoder = ReadCoilsResponse


@singleton
class DiscreteInputs(TypeCodec):
    """Modbus 'discrete input' data.
    This is a TypeCodec.
    """

    typ = 1
    encoder = ReadDiscreteInputsRequest
    decoder = ReadDiscreteInputsResponse


@singleton
class HoldingRegisters(TypeCodec):
    """Modbus 'holding register' data.
    This is a TypeCodec.
    """

    typ = 2
    encoder = ReadHoldingRegistersRequest
    decoder = ReadHoldingRegistersResponse


@singleton
class InputRegisters(TypeCodec):
    """Modbus 'input register' data.
    This is a TypeCodec.
    """

    typ = 3
    encoder = ReadInputRegistersRequest
    decoder = ReadInputRegistersResponse
