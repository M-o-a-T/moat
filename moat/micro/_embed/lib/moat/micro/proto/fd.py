import ctypes
import errno as E
import sys
from asyncio import TimeoutError, core, wait_for_ms

import ffi

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
    Access buffers backed by Unix file descriptors.

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
                print("R?", self, file=sys.stderr)
                await _rdq(self.fd_i)
        else:
            await _rdq(self.fd_i)
        ln = _read(self.fd_i.fileno(), buf, len(buf))
        if ln < 0:
            raise OSError(errno())
        if ln == 0:
            raise EOFError()

        m = memoryview(buf)
        if self.log:
            print("R:", bytes(m[:ln]), file=sys.stderr)
        return ln

    async def recv(self, n=512):
        buf = bytearray(n)
        ln = await self.recvi(buf)
        if ln <= len(buf) / 4:
            return buf[:ln]
        else:
            m = memoryview(buf)
            return m[:ln]

    async def send(self, buf, full=True):
        b = buf
        ll = 0
        async with self._wlock:
            while True:
                if self.log:
                    try:
                        await wait_for_ms(_wrq(self.fd_o), 100)
                    except TimeoutError:
                        print("W?", len(buf), file=sys.stderr)
                        await _wrq(self.fd_o)
                else:
                    await _wrq(self.fd_o)

                ln = _write(self.fd_o.fileno(), b, len(b))
                err = errno()
                if self.log:
                    if ln == len(b):
                        print("w:", bytes(b), file=sys.stderr)
                    elif ln == -1:
                        print("w:", bytes(b), "=E", errno(), file=sys.stderr)
                    else:
                        print("w:", bytes(b), "=", ln, file=sys.stderr)

                if ln < 0:
                    if err == E.ENOENT:
                        return
                    raise OSError(err)
                if ln == 0:
                    raise EOFError()
                ll += ln
                if ll == len(buf) or not full:
                    return ll
                b = memoryview(b)[ln:]
            return ll

    async def aclose(self):
        pass
