
"""
CRC fun.

We use the reversed algorithm because that requires fewer bit shifts.

We do not reverse the actual input.

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
            crc = ((crc >> 1) ^ self._poly) if crc&1 else (crc >> 1);
            bits -= 1
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
    _poly = 0x583 # 0x64d # 0x571
    _width = 11

class CRC16(_CRC):
    _poly = 0xAC9A # 0xBAAD
    _width = 16
    _depth = 8

class CRC32(_CRC):
    _poly = 0xEDB88320
    _width = 32
    _depth = 8

class CRC32n(CRC32):
    _depth = 4

if __name__ == "__main__":

    import re
    import sys
    import click

    def h_int(x):
        return int(x,16)

    @click.command(help="""\
CRC table calculator.

If your polynomial value has the high bit set (i.e. bit 2^depth)
we reverse it for you.

""")
    @click.option("-b","--bits",type=int,help="width of the polynomial")
    @click.option("-d","--depth",type=int,help="bits to calculate at once (table size)")
    @click.option("-p","--polynomial","poly",type=h_int,help="CRC polynomial to use (hex)")
    @click.option("-c","--c-table","t_c",is_flag=True,help="print a table for C code")
    @click.option("-f","--forth-table","t_f",is_flag=True,help="print Forth table+code")
    @click.option("-p","--python-table","t_p",is_flag=True,help="print Python table")
    @click.option("-h","--hexsample",is_flag=True,help="sample is hex bytes")
    @click.option("-F","--forth-prefix","p_f",is_flag=True,help="prefix Forth table with constants")
    @click.option("-S","--standard","std",type=int,help="set parameters to MoaT standard for CRC8/11/16")
    @click.argument("sample",nargs=-1)

    def main(bits,depth,poly,t_c,t_f,t_p,p_f,sample,hexsample,std):
        def pbd(p,b,d):
            nonlocal poly,bits,depth
            poly = poly or p
            bits = bits or b
            depth =depth or d
        if std:
            if std == 11:
                pbd(0x583,11,4)
            elif std == 8:
                pbd(0xa6,8,8)
            elif std == 16:
                pbd(0xAC9A,16,8)
            elif std == 32:
                pbd(0xEDB88320,32,8)
            else:
                raise click.UsageError(f"I only know std=8/11/16") 

        if not poly or not bits:
            raise click.UsageError("Need poly+bits")
        if not depth:
            depth = min(8,bits)

        if poly&(1<<bits): # reverse it
            pp = 0
            for _ in range(bits):
                pp = (pp<<1) | (poly&1)
                poly >>= 1
            poly = pp

        b = 1<<((bits-1).bit_length())
        if b not in (8,16,32):
            raise RuntimeError(f"I cannot do {bits} bits ({b})")

        class _C(_CRC):
            _poly=poly
            _width=bits
            _depth=depth
        C=_C()

        loglen = min(1<<((depth+1)//2), 256//b)
        lx = (bits+3)//4

        if t_p:
            print(f"uint{b}_t crc{bits}_{poly:0{lx}x}_{depth} = [")
            for i,v in enumerate(C._table):
                print(f"0x{v:0{lx}x},",end=" " if (i+1)%loglen else "\n")
            print("];")

        if t_c:
            print(f"uint{b}_t crc{bits}_{poly:0{lx}x}_{depth}[] = {{")
            for i,v in enumerate(C._table):
                print(f"0x{v:0{lx}x},",end=" " if (i+1)%loglen else "\n")
            print("};")

        if t_f:
            if b==8: # was: m_f
                comma = "h,"
            else:
                comma = "c," if b == 8 else "h," if b == 16 else ","

            cre = f"_t{b}" if p_f else "create"
            print(f"{cre} crc{bits}_{poly:0{lx}x}_{depth}")
            if p_f:
                if b == 8: # m_f:
                    print(f"${poly:0{lx}x} {depth} 8 lshift or h,")
                else:
                    print(f"${poly:0{lx}x} {comma} {depth} h,")
            for i,v in enumerate(C._table):
                if b == 8:
                    if i&1:
                        cma = f"or {comma}"
                    else:
                        cma = "8 lshift"
                else:
                    cma = comma
                print(f"${v:0{lx}x} {cma}", end=("  " if (i+1)%loglen else "\n"))

        if sample:
            C.reset()
            for samp in sample:
                if hexsample:
                    hb=int(samp,16)
                    if hb.bit_length() <= depth:
                        C.update(hb)
                    else:
                        for c in re.split("(..)",samp):
                            if c == '':
                                continue
                            c = int(c,16)
                            C.update_n(c,8)
                else:
                    for c in samp.encode("utf-8"):
                        C.update_n(c, 8)
            print(C.finish())

    main()
