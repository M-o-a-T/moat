# MoaT Python setup

# We hook our own reader into the micropython REPL
# which uses asyncio to fetch the actual data.
from __future__ import annotations

from micropython import alloc_emergency_exception_buf

alloc_emergency_exception_buf(300)

import os

if hasattr(os, "dupterm"):
    import io
    import sys
    from asyncio import core as _core
    from asyncio import run_until_complete as _wc
    from asyncio.stream import Stream as _str

    _w_read = _core._io_queue.queue_read
    _w_write = _core._io_queue.queue_write

    class MoaTconsole(io.IOBase):
        # public methods
        def __init__(self, s):
            # %s is a normal or async stream
            if not isinstance(s, _str):
                stream = _str(s)
            self.s = stream

        def write(self, buf):
            _wc(self.s.write("!"))
            return _wc(self.s.write(buf))

        def readinto(self, buf):
            return _wc(self.s.readinto(buf))

    cons = os.dupterm(None)
    if cons is None:
        cons = MoaTconsole(sys.stdin.buffer)
    os.dupterm(cons)
else:
    pass
