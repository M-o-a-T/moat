import ctypes

import ffi
import usys
from uasyncio import TimeoutError, core, wait_for_ms

C = ffi.open(None)
_err = ctypes.bytes_at(C.addr("errno"), 4)
_read = C.func("i", "read", "ipi")
_write = C.func("i", "write", "iPi")
_end = None


def _rdq(s):  # async
    yield core._io_queue.queue_read(s)


def _wrq(s):  # async
    yield core._io_queue.queue_write(s)


def errno():
    # XXX how to figure that out?
    global _end
    if _end is None:
        if ctypes.UINT32.from_bytes(_err, "little") == 0:
            return 0
        if ctypes.UINT32.from_bytes(_err, "little") < ctypes.UINT32.from_bytes(_err, "big"):
            _end = "little"
        else:
            _end = "big"
    return ctypes.UINT32.from_bytes(_err, _end)


class AsyncFD:
    """
    Access streams directly.

    This is a workaround for MicroPython's stdio on Unix, which
    doesn't have a binary mode via 'sys.stdin/out.buffer'. *Sigh*.
    """

    def __init__(self, fd_i, fd_o=None, log=False):
        self.fd_i = fd_i
        self.fd_o = fd_o if fd_o is not None else fd_i
        self.log = log

    async def recv(self, n=512):
        if self.log:
            try:
                await wait_for_ms(_rdq(self.fd_i), 100)
            except TimeoutError:
                print("R?", n, file=usys.stderr)
                await _rdq(self.fd_i)
        else:
            await _rdq(self.fd_i)
        b = bytes(n)
        l = _read(self.fd_i.fileno(), b, n)
        if l < 0:
            raise OSError(errno())
        if l <= n / 4:
            if self.log:
                print("R:", b[:l], file=usys.stderr)
            return b[:l]
        else:
            m = memoryview(b)
            if self.log:
                print("R:", bytes(m[:l]), file=usys.stderr)
            return m[:l]

    async def send(self, buf):
        if self.log:
            try:
                await wait_for_ms(_wrq(self.fd_o), 100)
            except TimeoutError:
                print("W?", len(buf), file=usys.stderr)
                await _wrq(self.fd_o)
        else:
            await _wrq(self.fd_o)
        l = _write(self.fd_o.fileno(), buf, len(buf))
        if self.log:
            if l == len(buf):
                print("w:", bytes(buf), file=usys.stderr)
            elif l == -1:
                print("w:", bytes(buf), "=E", errno(), file=usys.stderr)
            else:
                print("w:", bytes(buf), "=", l, file=usys.stderr)

        if l < 0:
            raise OSError(errno())
        return l

    async def aclose(self):
        pass
