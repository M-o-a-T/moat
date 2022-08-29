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

    def __call__(self):
        raise RuntimeError("This value doesn't.")


class InaccessibleValue(BaseValue):  # duck-types but does NOT interit BaseValue
    """This register range must not be accessed.

    Use an instance of this type (with appropriate length)
    to force splitting a request into multiple parts.

    :param len: The length of the block that may not be accessed.
    """

    def __init__(self, len):
        self.len = len


@singleton
class IntValue(BaseValue):
    """Simplest-possible value, one register.

    This is a BaseValue instance.
    """

    len = 1

    def __call__(self, regs):
        return regs[0]


@singleton
class LongValue(BaseValue):
    """32-bit integer, two registers, standard (big-endian) word order.

    This is a BaseValue instance.
    """

    len = 2

    def __call__(self, regs):
        return regs[0] * 65536 + regs[1]


@singleton
class SwappedLongValue(BaseValue):
    """32-bit integer, two registers, little-endian word order.

    This is a BaseValue instance.
    """

    len = 2

    def __call__(self, regs):
        return regs[1] * 65536 + regs[0]


@singleton
class QuadValue(BaseValue):
    """64-bit integer, four registers, standard (big-endian) word order.

    This is a BaseValue instance.
    """

    len = 4

    def __call__(self, regs):
        return ((regs[0] * 65536 + regs[1]) * 65536 + regs[2]) * 65536 + regs[3]


@singleton
class SwappedQuadValue(BaseValue):
    """64-bit integer, four registers, little-endian word order.

    This is a BaseValue instance.
    """

    len = 4

    def __call__(self, regs):
        return ((regs[3] * 65536 + regs[2]) * 65536 + regs[1]) * 65536 + regs[0]


@singleton
class SignedIntValue(BaseValue):
    """one register, signed.

    This is a BaseValue instance.
    """

    len = 1

    def __call__(self, regs):
        res = regs[0]
        if res >= 1 << 15:
            res -= 1 << 16
        return res


@singleton
class SignedLongValue(BaseValue):
    """two registers, signed.

    This is a BaseValue instance.
    """

    len = 2

    def __call__(self, regs):
        res = regs[0] * 65536 + regs[1]
        if res >= 1 << 31:
            res -= 1 << 32
        return res


@singleton
class SwappedSignedLongValue(BaseValue):
    """two registers, signed, swapped.

    This is a BaseValue instance.
    """

    len = 2

    def __call__(self, regs):
        res = regs[1] * 65536 + regs[0]
        if res >= 1 << 31:
            res -= 1 << 32
        return res


SignedSwappedLongValue = SwappedSignedLongValue


@singleton
class SignedQuadValue(BaseValue):
    """four registers, signed.

    This is a BaseValue instance.
    """

    len = 4

    def __call__(self, regs):
        res = ((regs[0] * 65536 + regs[1]) * 65536 + regs[2]) * 65536 + regs[3]
        if res >= 1 << 63:
            res -= 1 << 64
        return res


@singleton
class SwappedSignedQuadValue(BaseValue):
    """four registers, signed, swapped.

    This is a BaseValue instance.
    """

    len = 4

    def __call__(self, regs):
        res = ((regs[3] * 65536 + regs[2]) * 65536 + regs[1]) * 65536 + regs[0]
        if res >= 1 << 63:
            res -= 1 << 64
        return res


SignedSwappedQuadValue = SwappedSignedQuadValue


@singleton
class FloatValue(BaseValue):
    """network-ordered floating point.

    This is a BaseValue instance.
    """

    len = 2

    def __call__(self, regs):
        return struct.unpack(">f", struct.pack(">2H", *regs))


@singleton
class SwappedFloatValue(BaseValue):
    """network-ordered floating point.

    This is a BaseValue instance.
    """

    len = 2

    def __call__(self, regs):
        return struct.unpack(">f", struct.pack(">2H", regs[1], regs[0]))


@singleton
class DoubleValue(BaseValue):
    """network-ordered accurate floating point.

    This is a BaseValue instance.
    """

    len = 4

    def __call__(self, regs):
        return struct.unpack(
            ">d", struct.pack(">4H", regs[0], regs[1], regs[2], regs[3])
        )


@singleton
class SwappedDoubleValue(BaseValue):
    """network-ordered accurate floating point.

    This is a BaseValue instance.
    """

    len = 4

    def __call__(self, regs):
        return struct.unpack(
            ">d", struct.pack(">4H", regs[3], regs[2], regs[1], regs[0])
        )


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
