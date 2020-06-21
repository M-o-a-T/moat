"""
The byte-sized minifloat accepted by `mini2byte` and returned by
`byte2mini` has no sign bit, 4 bit exponent, 4 bit mantissa, no NaN or
overrun/infinity signalling.

It can thus accept values from 0…32 in steps of 0.25, 0.5 to 48, 1 to 64,
and so on until steps of 4096 from 65536 to 126976.
"""

def mini2byte(f):
    """
    Convert a float to a byte-sized minifloat:
    """

    f = int(f*4+0.5)
    if f <= 32:
        return f
    exp = 1
    while f >= 32: # not an error because of normalization
        f >>= 1
        exp += 1
    return (exp<<4) | (f&0xf)

def byte2mini(m):
    """
    Convert a byte-sized minifloat back to a number.
    """
    if m <= 32:
        return m/4
    exp = (m>>4)-1
    m = 16+(m&0xf)
    return (1<<exp)*m/4


if __name__ == "__main__":
    for x in range(256):
        print(x,byte2mini(x),mini2byte(byte2mini(x)))

    
