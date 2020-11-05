"""
The byte-sized minifloat accepted by `mini2byte` and returned by
`byte2mini` has no sign bit, 4 bit exponent, 4 bit mantissa, no NaN or
overrun/infinity signalling.

It can thus accept values from 0…32 in steps of 0.25, 0.5 to 48, 1 to 64,
and so on until steps of 4096 from 65536 to 126976.
"""

class CtxObj:
    """
    Add an async context manager that calls `_ctx` to run the context.

    Usage::
        class Foo(CtxObj):
            @asynccontextmanager
            async def _ctx(self):
                yield self # or whatever

        async with Foo() as self_or_whatever:
            pass
    """
    __ctx = None
    def __aenter__(self):
        if self.__ctx is not None:
            breakpoint()
            raise RuntimeError("Double context")
        self.__ctx = ctx = self._ctx()
        return ctx.__aenter__()

    def __aexit__(self, *tb):
        ctx,self.__ctx = self.__ctx,None
        return ctx.__aexit__(*tb)

# minifloat granularity
MINI_F = 1/4

def mini2byte(f):
    """
    Convert a float to a byte-sized minifloat:
    """

    f = int(f/MINI_F+0.5)
    if f <= 32:  # or 16, doesn't matter
        return f
    exp = 1
    while f >= 32: # not an error because of normalization
        f >>= 1
        exp += 1
    if exp > 15:
        return 0xFF
    return (exp<<4) | (f&0xf)

def byte2mini(m):
    """
    Convert a byte-sized minifloat back to a number.
    """
    if m <= 32:  # or 16, doesn't matter
        return m*MINI_F
    exp = (m>>4)-1
    m = 16+(m&0xf)  # normalization
    return (1<<exp)*m*MINI_F


if __name__ == "__main__":
    for x in range(256):
        print(x,byte2mini(x),mini2byte(byte2mini(x)))

