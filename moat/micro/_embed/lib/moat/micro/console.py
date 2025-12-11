"""
Console class.

Set up from the root "main.py".
"""

from __future__ import annotations

import io
import os
import sys

from asyncio import create_task, run_until_complete, sleep_ms

from moat.lib.ring import RingBuffer
from moat.micro.cmd.base import BaseCmd
from moat.util.compat import ACM, AC_exit, AC_use, CancelledError, Event, idle

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.lib.cmd.msg import Msg

    from collections.abc import Callable

current: Console | None = None


class Main:
    """
    This is a singleton-ish class that holds the main execution context
    and (possibly) the console reference.
    """

    console: Console | None = None

    def __init__(self, wr_exc: Callable):
        ACM(self)

        self.evt = evt = Event()
        self.wait = evt.wait
        self.wr_exc = wr_exc

    # There is no "start", that's done by `Cmd.setup`.

    def stop(self):
        "Stop using the console, if any."
        if self.console is not None:
            self.console.stop()

    def die(self, exc: Exception):
        "Stop using the console and unwind."
        self.stop()
        if not isinstance(exc, CancelledError):
            self.wr_exc(exc)
        while self._AC_:
            run_until_complete(create_task(AC_exit(self, type(exc), exc, None)))

    def maybe_end(self, exc: Exception | None = None):
        "Stop if no console"
        if self.console is None:
            run_until_complete(idle())
            run_until_complete(AC_exit(self, type(exc) if exc is not None else None, exc, None))
            if self._AC_:
                print("ERROR exit nesting?", file=sys.stderr)
                while self._AC_:
                    run_until_complete(
                        AC_exit(self, type(exc) if exc is not None else None, exc, None)
                    )


main: Main = None  # set by moat.micro.main


class Console(io.IOBase):
    """
    The console driver that allows MoaT to run in the background.

    Config:
        keep: flag whether to keep the original console driver
        sleep: cycle time for asyncio
    """

    _term = None
    _wr_evt: Event | None = None
    _rd_evt: Event | None = None

    def __init__(self, cfg):
        self.cfg = cfg
        self._AC_ = main._AC_

        self._rb = RingBuffer(128)
        self._wb = RingBuffer(512)

    def write(self, buf: bytes) -> int:
        "Console write"
        if self._wr_evt is not None:
            self._wr_evt.set()
        return self._wb.write(buf)

    async def get_out(self, buf: bytearray) -> int:
        "extract from write buffer"
        if not len(self._wb):
            self._wr_evt = Event()
            await self._wr_evt.wait()
            self._wr_evt = None
        return self._wb.readinto(buf)

    def readinto(self, buf):
        "Console read"
        if len(self._rb) == 0:
            if self._rd_evt is not None:
                self._rd_evt.set()
            try:
                run_until_complete(sleep_ms(self.cfg.get("sleep", 20)))
            except BaseException as exc:
                self.__exit__()
                main.die(exc)
                run_until_complete(AC_exit(self, type(exc), exc, None))
                raise

        return self._rb.readinto(buf)

    async def put_in(self, buf) -> None:
        "feed to read buffer"
        while (lb := len(buf)) > 0:
            if buf.n_free() == 0:
                self._rd_evt = Event()
                await self._rd_evt.wait()
                self._rd_evt = None
            n = self._rb.write(buf, drop=False)
            if n == lb:
                return
            buf = memoryview(buf[n:])

    def start(self):
        "Start using this."
        if main.console is not None:
            raise RuntimeError("Already up")

        if self.cfg["keep"]:
            os.dupterm(self, 1)
        else:
            self._term = os.dupterm(self, 0)
        main.console = self

    __enter__ = start

    def stop(self):
        "Stop using this."
        if main.console is self:
            main.console = None
        if self.cfg["keep"]:
            os.dupterm(None, 1)
        else:
            os.dupterm(self._term, 0)
            self._term = None

    def __exit__(self, *exc):
        self.stop()


class Cmd(BaseCmd):
    """
    The command that attaches and runs a console.

    See :cls:`Console` for configuration.
    """

    async def setup(self):
        "Create a console"
        await super().setup()
        await AC_use(self, Console(self.cfg))

    doc_r = dict(_d="Read console data", _0="int:maxlength (default 32)")

    async def stream_r(self, msg: Msg):
        "read from stdout/stderr"
        buf = bytearray(msg.get(0, 32))
        if msg.can_stream:
            async with msg.stream_w() as ms:
                while True:
                    res = await current.get_out(buf)
                    await ms.send(buf[:res])
        else:
            res = await current.get_out(buf)
            if not res:
                buf = b""
            else:
                buf = memoryview(buf)[:res]
            await self.result(buf)

    doc_w = dict(_d="Write console data", _0="bytes: data")

    async def stream_w(self, msg: Msg):
        "write, goes to stdin"
        if msg.can_stream:
            with msg.stream_r() as ms:
                async for m in ms:
                    await current.put_in(m[0])
        else:
            await current.put_in(msg[0])
