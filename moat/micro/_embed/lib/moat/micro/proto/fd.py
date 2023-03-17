import ctypes

import ffi
import usys
from uasyncio import TimeoutError, core, wait_for_ms

C = ffi.open(None)
_err = ctypes.bytes_at(C.addr("errno"), 4)
_read = C.func("i", "read", "ipi")
_write = C.func("i", "write", "iPi")
_end = None

from moat.micro.compat import Lock

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
        self._wlock = Lock()

    async def recvi(self, buf):
        if self.log:
            try:
                await wait_for_ms(_rdq(self.fd_i), 100)
            except TimeoutError:
                print("R?", n, file=usys.stderr)
                await _rdq(self.fd_i)
        else:
            await _rdq(self.fd_i)
        l = _read(self.fd_i.fileno(), buf, len(buf))
        if l < 0:
            raise OSError(errno())
        if l == 0:
            raise EOFError()

        m = memoryview(buf)
        if self.log:
            print("R:", bytes(m[:l]), file=usys.stderr)
        return l

    async def recv(self, n=512):
        buf = bytearray(n)
        l = await self.recvi(buf)
        if l <= len(buf) / 4:
            return b[:l]
        else:
            m = memoryview(buf)
            return m[:l]

    async def send(self, buf, full=True):
        b = buf
        ll = 0
        async with self._wlock:
            while True:
                if self.log:
                    try:
                        await wait_for_ms(_wrq(self.fd_o), 100)
                    except TimeoutError:
                        print("W?", len(buf), file=usys.stderr)
                        await _wrq(self.fd_o)
                else:
                    await _wrq(self.fd_o)

                l = _write(self.fd_o.fileno(), b, len(b))
                if self.log:
                    if l == len(b):
                        print("w:", bytes(b), file=usys.stderr)
                    elif l == -1:
                        print("w:", bytes(b), "=E", errno(), file=usys.stderr)
                    else:
                        print("w:", bytes(b), "=", l, file=usys.stderr)

                if l < 0:
                    raise OSError(errno())
                if l == 0:
                    raise EOFError()
                ll += l
                if ll == len(buf) or not full:
                    return ll
                b = memoryview(b)[l:]
            return ll

    async def aclose(self):
        pass
