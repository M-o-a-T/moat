"""
Map strings+kinds to modbuys types
"""

from moat.modbus.types import (
    ByteValue,
    DoubleValue,
    FloatValue,
    IntValue,
    LongValue,
    QuadValue,
    SignedIntValue,
    SignedLongValue,
    SignedQuadValue,
    StringValue,
    SwappedByteValue,
    SwappedDoubleValue,
    SwappedFloatValue,
    SwappedLongValue,
    SwappedQuadValue,
    SwappedSignedLongValue,
    SwappedSignedQuadValue,
    SwappedStringValue,

    Coils,
    DiscreteInputs,
    HoldingRegisters,
    InputRegisters,
)

map_type = {
    "raw": IntValue,
    "u1": IntValue,
    "U1": IntValue,
    "u2": LongValue,
    "U2": SwappedLongValue,
    "u4": QuadValue,
    "U4": SwappedQuadValue,
    "s1": SignedIntValue,
    "S1": SignedIntValue,
    "s2": SignedLongValue,
    "S2": SwappedSignedLongValue,
    "s4": SignedQuadValue,
    "S4": SwappedSignedQuadValue,
    "f2": FloatValue,
    "F2": SwappedFloatValue,
    "f4": DoubleValue,
    "F4": SwappedDoubleValue,
    "c#": StringValue,
    "C#": SwappedStringValue,
    "b#": ByteValue,
    "B#": SwappedByteValue,
}


