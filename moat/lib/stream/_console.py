"""
Console data handling for stream layers.
"""

from __future__ import annotations

from moat.lib.micro import Event


class _CReader:
    """
    A mix-in that processes incoming console data.
    """

    def __init__(self, cons: bool | int):
        if cons is True:
            try:
                import machine  # noqa: PLC0415,F401
            except ImportError:
                cons = 32768
            else:
                cons = 240
        self.cevt = Event()
        self.cpos = 0
        self.cbuf = bytearray(cons)
        self.cons = cons
        self.intr = 0

    async def crd(self, buf: bytearray):
        """read waiting console data"""
        if not self.cons:
            raise EOFError
        if not self.cpos:
            await self.cevt.wait()
            self.cevt = Event()
        n = min(len(buf), self.cpos)
        buf[:n] = self.cbuf[:n]
        if n < self.cpos:
            self.cbuf[: self.cpos - n] = self.cbuf[n : self.cpos]
            self.cpos -= n
        else:
            self.cpos = 0
        return n

    def cput(self, b: int):
        """store a byte in the console buffer"""
        if self.cpos == len(self.cbuf):
            if len(self.cbuf) > 100:
                bfull = b"\n?BUF\n"
                self.cbuf[0 : len(bfull)] = bfull
                self.cpos = len(bfull)
            else:
                self.cpos = 0
        if b != 3:
            self.intr = 0
        elif self.intr > 2:
            raise KeyboardInterrupt
        else:
            self.intr += 1
        self.cbuf[self.cpos] = b
        self.cpos += 1
        self.cevt.set()
