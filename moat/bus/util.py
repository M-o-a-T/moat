"""
This module implements a minifloat, i.e. an approximation for
floating-point numbers that fits in a byte.

The MoaT bus uses these for timeouts in messages.
"""

from __future__ import annotations


# minifloat granularity
MINI_F = 1/4

def mini2byte(f):
    """
    Convert a float to a byte-sized minifloat.

    The byte-sized minifloat accepted by `mini2byte` and returned by
    `byte2mini` has no sign bit, 4 bit exponent, 4 bit mantissa, no NaN or
    overrun/infinity signalling (while 0xFF can be used as such if
    desired, that's not covered by this code).

    It can thus accept values from 0…8 in steps of 0.25, 0.5 to 16, 1 to 32,
    and so on, until steps of 4096 from 65536 to 126976 / 122880, which is
    more than a day. It is thus suited well for timeouts with variable
    granularity that don't take up much space.
    """

    f = int(f/MINI_F+0.5)
    if f <= 0x20:  # < 0x10: in theory, but the result is the same
        return f  # exponent=0 is denormalized
    exp = 1
    while f > 0x1F: # the top bit is set because of normalization
        f >>= 1
        exp += 1
    if exp > 0x0F:
        return 0xFF
    return (exp<<4) | (f&0x0F)
    # The mantissa is normalized, i.e. the top bit is always 1, thus it is
    # discarded and not included in the result.

def byte2mini(m):
    """
    Convert a byte-sized minifloat back to a number.
    """
    if m <= 32:  # or 16, doesn't matter
        return m*MINI_F
    exp = (m>>4)-1
    m = 0x10+(m&0xf)  # normalization
    return (1<<exp)*m*MINI_F


if __name__ == "__main__":
    for x in range(256):
        print(x,byte2mini(x),mini2byte(byte2mini(x)))

