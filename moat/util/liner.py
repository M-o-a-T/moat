""

from __future__ import annotations

import sys
from inspect import iscoroutinefunction

from moat.util.compat import (
    ACM,
    AC_exit,
    Event,
    TaskGroup,
    TimeoutError,  # noqa:A004
    is_async,
    wait_for_ms,
)


async def _no_op():
    pass


class Liner:
    """
    A way to collect output until timeout-or-EOL
    and then to print it all at once.


    Args:
        prefix:
            Text to emit at the start of each line.
        incomplete:
            String to add to incomplete lines.
        writer:
            Called to write complete lines. Must not append linefeed.
        delay:
            Milliseconds until a line is declared incomplete. Default 100.

    If the writer is async, so is calling this obj with data.
    """

    def __init__(self, prefix="", incomplete="…", writer=sys.stdout.write, delay=100):
        self.prefix = prefix
        self.incomplete = incomplete
        self.writer = writer
        self.delay = delay

        self.buf = bytearray()

    async def __aenter__(self):
        AC = ACM(self)
        try:
            self.evt = Event()
            self._tg = tg = await AC(TaskGroup())
            tg.start_soon(self._flush)
        except BaseException as exc:
            await AC_exit(self, type(exc), exc, None)
            raise
        return self

    async def __aexit__(self, *exc):
        self._tg.cancel()
        if self.buf:
            await self._partial(True)
        return await AC_exit(self, *exc)

    async def _flush(self):
        # Background task to write incomplete lines
        while True:
            try:
                await wait_for_ms(self.delay, self.evt.wait)
            except TimeoutError:
                pass
            else:
                # Event triggered
                self.evt = Event()
                continue

            # Event did not trigger
            if self.buf:
                await self._partial()

            # now wait for the next possibly-incomplete line
            await self.evt.wait()
            self.evt = Event()

    async def _partial(self, end: bool = False):
        pr = self.buf.decode("utf-8")
        self.buf = None if end else bytearray()

        res = self.writer(self.prefix + pr + self.incomplete + ("-END-" if end else "") + "\n")
        if is_async(res):
            await res

    def __call__(self, data):
        """
        Writer.
        """
        if isinstance(data, memoryview):
            data = bytes(data)
        buf = self.buf
        if buf is None:
            # after end. Oops, async timing is nontrivial.
            buf = data
            idx = len(buf)
        else:
            buf += data
            idx = buf.rfind(b"\n")
        try:
            if idx != -1:
                pr = buf[:idx].decode("utf-8").replace("\n", f"\n{self.prefix}")
                self.buf = buf[idx + 1 :]
                return self.writer(self.prefix + pr + "\n")
            elif iscoroutinefunction(self.writer):
                return _no_op()
        finally:
            if self.buf:
                self.evt.set()
