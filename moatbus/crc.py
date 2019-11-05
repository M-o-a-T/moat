
"""
CRC fun.

We use the reversed algorithm because that requires fewer bit shifts.

We do not reverse the actual input. A "real" CRC check requires that the
CRC sum over data plus CRC is zero (or -1). but we can't do that anyway,
so we don't bother.

"""

import functools

def _bitrev(x, n):
    y = 0
    for i in range(n):
        y = (y << 1) | (x & 1)
        x = x >> 1
    return y

def _bytecrc_r(crc, poly, depth):
    for i in range(depth):
        if crc & 1:   
            crc = (crc >> 1) ^ poly
        else:
            crc = crc >> 1
    return crc

class _CRCmeta(type):
    def __new__(typ, name, bases, dct):
        poly = dct.get('_poly', None)
        if poly is None:
            return super().__new__(typ, name, bases, dct)
        width = dct['_width']
        if poly & ((1<<width)-1) != poly:
            raise RuntimeError("This polynomial is too wide")
        #poly = _bitrev(poly, width)

        cls = super().__new__(typ, name, bases, dct)
        return cls

class _CRC(metaclass=_CRCmeta):
    _table = None # filled by metaclasse
    _width = None # degree of polynomial
    _poly = None # non-reversed polynomial, no 2^_width term!

    """
    Simple CRC update function. @n is the bit length of the input.
    """
    def __init__(self, bits=None):
        self.crc = 0
        if bits is None:
            bits = self._depth
        self._bits = bits
        self._table = table = []
        poly = self._poly
        for b in range(1<<bits):
            table.append(_bytecrc_r(b,poly,bits))

    def reset(self):
        self.crc = 0

    def update(self, data):
        """
        Mix a `self._bits`-bit data word into the CRC.

        Equal to, but faster than, `crc.update_n(data,crc._bits)`.
        """
        self.crc = self._table[(data ^ self.crc) & ((1<<self._bits)-1)] ^ (self.crc>>self._bits)

    def update_n(self, data, bits):
        """
        Mix an n-bit data word into the CRC.
        """
        d = self._bits
        t = self._table
        crc = self.crc
        while bits >= d:
            crc = t[(data ^ crc) & ((1<<d)-1)] ^ (crc>>d)
            bits -= d
            data >>= d
        assert data == (data & ((1<<d)-1))
        crc ^= data;
        while bits:
            crc = ((crc >> 1) ^ POLY) if crc&1 else (crc >> 1);
        self.crc = t[((data ^ crc) & ((1<<bits)-1))] ^ (crc>>bits)

    def finish(self):
        return self.crc

class CRC6(_CRC):
    _poly = 0x2c
    _width = 6

class CRC8(_CRC):
    _poly = 0xa6
    _width = 8

class CRC11(_CRC):
    _poly = 0x571 # 0x64d # 0x583
    _width = 11

class CRC16(_CRC):
    _poly = 0xAC9A # 0xBAAD
    _width = 16
    _depth = 8

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 2:
        _,w,*x = sys.argv
        x=[int(v,16) for v in x]
        w=int(w)
        c=CRC11(w)
        for i,v in enumerate(x):
            if i == 0:
                p = v
                continue
            v^=p
            c.update(v)
            print(("%2d %02x %03x" if w>4 else "%2d %01x %03x") % (i,v, c.crc), end=("  " if i%8 else "\n"))
        print("")

    else:
        #print(CRC6._table)
        #print(CRC8._table)
        print(CRC16(8)._table)
        #print(CRC16._table)
