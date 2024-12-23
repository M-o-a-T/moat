"""
Map strings+kinds to modbuys types
"""

from __future__ import annotations

from functools import partial

from moat.modbus.types import (
    BitValue,
    InvBitValue,
    ByteValue,
    Coils,
    DiscreteInputs,
    DoubleValue,
    FloatValue,
    HoldingRegisters,
    InputRegisters,
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
)

map_type = {
    "raw": IntValue,
    "x": BitValue,
    "X": InvBitValue,
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


def get_type(s):
    """Return the type from shortname (like 'u2')"""
    hashkey = f"{s[0]}#"
    if hashkey in map_type:
        return partial(map_type[hashkey], int(s[1:]))
    else:
        return map_type[s]


def get_type2(s, l):
    """Return the type from longname and length (like 'int' '2')"""
    IntMap = [
        [
            {
                1: SignedIntValue,
                2: SignedLongValue,
                4: SignedQuadValue,
            },
            {
                1: IntValue,
                2: LongValue,
                4: QuadValue,
            },
        ],
        [
            {
                1: SignedIntValue,
                2: SwappedSignedLongValue,
                4: SwappedSignedQuadValue,
            },
            {
                1: IntValue,
                2: SwappedLongValue,
                4: SwappedQuadValue,
            },
        ],
    ]
    FloatMap = [
        {
            2: FloatValue,
            4: DoubleValue,
        },
        {
            2: SwappedFloatValue,
            4: SwappedDoubleValue,
        },
    ]
    swapped = False
    unsigned = False

    os = s
    if s[0] == "s" and s != "str":
        s = s[1:]
        swapped = True
    if s[0] == "u":
        s = s[1:]
        unsigned = True
    if s == "int":
        return IntMap[swapped][unsigned][l]

    if not unsigned:
        if s == "float":
            return FloatMap[swapped][l]
        if s == "byte":
            return partial([ByteValue, SwappedByteValue][swapped], length=l)
        if s == "str":
            return partial([ByteValue, SwappedByteValue][swapped], length=l)
        if not swapped and l == 1:
            if s == "bit":
                return BitValue
            if s == "invbit":
                return InvBitValue
    raise KeyError(f"Unknown: {os}:{l}")


map_kind = {"c": Coils, "d": DiscreteInputs, "h": HoldingRegisters, "i": InputRegisters}


def get_kind(s):
    """Return the value kind from name"""
    return map_kind[s[0]]
