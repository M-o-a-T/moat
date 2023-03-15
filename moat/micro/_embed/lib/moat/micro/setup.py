# MoaT Python setup

# We hook our own reader into the micropython REPL
# which uses uasyncio to fetch the actual data.

# This does not work on rp2 at the moment because
# natively neither uart nor usb use dupterm

from micropython import alloc_emergency_exception_buf

alloc_emergency_exception_buf(300)

try:
    import rp2
except ImportError:
    import sys

    import uio
    import uos
    from uasyncio import core as _core
    from uasyncio import run_until_complete as _wc
    from uasyncio.stream import Stream as _str

    _w_read = _core._io_queue.queue_read
    _w_write = _core._io_queue.queue_write

    class MoaTconsole(uio.IOBase):
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

    cons = uos.dupterm(None)
    if cons is None:
        cons = MoaTconsole(sys.stdin.buffer)
    uos.dupterm(cons)
else:
    pass
