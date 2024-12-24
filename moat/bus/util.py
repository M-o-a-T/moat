"""
This module implements a minifloat, i.e. an approximation for
floating-point numbers that fits in a byte.

The MoaT bus uses these for timeouts in messages.
"""

from __future__ import annotations


# minifloat granularity
MINI_F = 1 / 4


def mini2byte(f: float) -> int:
    """
    Convert a float to a byte-sized minifloat.

    The byte-sized minifloat accepted by `mini2byte` and returned by
    `byte2mini` has no sign bit, 4 bit exponent, 4 bit mantissa, no NaN or
    overrun/infinity signalling (while 0xFF can be used as such if
    desired, that's not covered by this code).

    It can thus represens values from 0…8 in steps of 0.25, 0.5 to 16, 1 to 32,
    and so on, until steps of 4096 from 65536 to 126976 (0xFF) / 122880
    (0xFE), which is more than a day if you interpret minifloat values as
    seconds. It is thus suited well for timeouts with variable granularity
    that don't take up more space than absolutely necessary.
    """

    if f < 0:
        raise ValueError("Minifloats can't be negative")
    f = int(f / MINI_F + 0.5)
    if f <= 0x20:  # < 0x10: in theory, but the result is the same
        return f  # exponent=0 is denormalized
    exp = 1
    while f > 0x1F:  # scale the result
        f >>= 1
        exp += 1
    if exp > 0x0F:
        return 0xFF
    # The result is normalized: since the top bit is always 1 when the
    # exponent is non-zero, we can simply not transmit it and gain another
    # bit of "accuracy".
    return (exp << 4) | (f & 0x0F)


def byte2mini(m: int) -> float:
    """
    Convert a byte-sized minifloat back to a number.

    See `mini2byte` for details.
    """
    if m <= 32:  # or 16, doesn't matter
        return m * MINI_F

    exp = (m >> 4) - 1
    m = 0x10 + (m & 0xF)  # normalization
    return (1 << exp) * m * MINI_F


if __name__ == "__main__":
    for x in range(256):
        print(x, byte2mini(x), mini2byte(byte2mini(x)))
