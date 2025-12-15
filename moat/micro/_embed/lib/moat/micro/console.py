"""
Console class.

Set up from the root "main.py".
"""

from __future__ import annotations

import io
import os
import sys

from asyncio import create_task, run_until_complete

from moat.lib.ring import RingBuffer
from moat.lib.ring.aio import RingBuffer as AioRingBuffer
from moat.micro.cmd.base import BaseCmd
from moat.util.compat import (
    ACM,
    AC_exit,
    AC_use,
    CancelledError,
    Event,
    TaskGroup,
    TimeoutError,  # noqa:A004
    ValueEvent,
    wait_for_ms,
)

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from asyncio import Task

    from moat.lib.cmd.msg import Msg

    from collections.abc import Awaitable, Callable

#
# The purpose of this code is to run asyncio from the console read loop.
#
# The main task (moat.micro.main) creates the Main class, starts the
# dispatch task, and saves it in `main.main_task`. The context frames are
# also attached to the `main` object.
#
# Closing the console cancels the main task and unwinds the contexts.
# After that the system should be in the same state it would be in if MoaT
# had ended without running the REPL behind the scenes (or rather, running
# the REPL while processing MoaT behind the scenes).


class Main:
    """
    This is a singleton-ish class that holds the main execution context
    and (possibly) the console reference.
    """

    console: Console | None = None
    main_task: Task = None
    user_task: Task = None
    tg: TaskGroup = None

    def __init__(self, wr_exc: Callable):
        ACM(self)

        self.evt = evt = Event()
        self.wait = evt.wait
        self.wr_exc = wr_exc

    def start(self, cons: Console):
        """
        Start using this console.

        Called from `Console.start`.
        """
        if self.main_task is None:
            raise RuntimeError("main not set")

        import moat  # noqa:PLC0415

        moat.call = call
        moat.bg = bg

        self.console = cons
        self.evt.set()

    def stop(self):
        """
        Stop using the console, if any.

        Called from the MoaT main code.
        """
        if self.console is not None:
            import moat  # noqa:PLC0415

            moat.call = None
            if self.main_task is not None:
                self.main_task.cancel()
                self.main_task = None
            try:
                self.console.stop()
            finally:
                self.console = None

    def die(self, exc: Exception):
        """
        Stop using the console and unwind.

        Called from the MoaT main code.
        """
        run_until_complete(create_task(self.die_(exc)))

    async def die_(self, exc: Exception):
        "async version of `die`."
        self.stop()
        if not isinstance(exc, CancelledError):
            self.wr_exc(exc)
        while self._AC_:
            await AC_exit(self, type(exc), exc, None)


main: Main = None  # set by moat.micro.main


def bg(p, *a, **k) -> ValueEvent:
    """
    Returns a ValueEvent that encapsulates the result of running @p,
    and which allows it to be cancelled.

    Installed as 'moat.bg'.
    """
    evt = ValueEvent()

    async def run_(evt, p, a, k):
        try:
            evt.set(await p(*a, **k))
        except BaseException as exc:
            evt.set(exc)

    async def run(evt, p, a, k):
        evt.scope = main.tg.spawn(run_, evt, p, a, k)
        return evt

    run_until_complete(create_task(run(evt, p, a, k)))
    return evt


def call(p, *a, **k):
    """
    Returns the result of running @p asynchronously.

    A REPL input that consists of a single Ctrl-C will terminate the call.

    Installed as 'moat.call'.
    """
    evt = bg(p, *a, **k)
    return run_until_complete(evt.get())


class Console(io.IOBase):
    """
    The console driver that allows MoaT to run in the background.

    Config:
        keep: flag whether to keep the original console driver
        sleep: cycle time for asyncio
        repl: flag whether to 'return' to the REPL.
    """

    _term = None
    _wr_evt: Event | None = None

    def __init__(self, cfg):
        self.cfg = cfg
        self._AC_ = main._AC_

        self._rb = AioRingBuffer(128)
        self._wb = RingBuffer(512)

    def write(self, buf: bytes) -> int:
        "Console write"
        if not buf:
            return 0
        if self._wr_evt is not None:
            self._wr_evt.set()
        return self._wb.write(buf)

    async def get_out(self, buf: bytearray) -> int:
        "extract from write buffer"
        while not len(self._wb):
            self._wr_evt = Event()
            try:
                await self._wr_evt.wait()
            finally:
                self._wr_evt = None
        return self._wb.readinto(buf)

    def read(self, n):
        "Console read"
        # if self._wb.n_avail < 100: self.write(b"R")
        buf = bytearray(n)
        try:
            res = run_until_complete(
                create_task(wait_for_ms(self.cfg.get("sleep", 20), self._rb.readinto, buf))
            )
        except TimeoutError:
            # if self._wb.n_avail < 100: self.write(b"_")
            return None
        except BaseException as exc:
            self.__exit__()
            main.die(exc)
            run_until_complete(AC_exit(self, type(exc), exc, None))
            raise
        else:
            # if self._wb.n_avail < 100: self.write(f"r{res} ".encode("utf-8"))
            if res < n:
                buf[res:] = b""
            return buf

    def ioctl(self, req, flags):
        """
        ioctl to test for readiness.
        """
        # if self._wb.n_avail < 100: self.write(f"IOC {req} {flags}\n".encode("utf-8"))
        if req == 3:  # MP_STREAM_POLL
            if flags & 1:
                try:
                    if not len(self._rd):
                        run_until_complete(
                            create_task(
                                wait_for_ms(self.cfg.get("sleep", 20), self._rb.wait_avail)
                            )
                        )
                except TimeoutError:
                    # if self._wb.n_avail < 100: self.write(b"-")
                    flags &= ~1

            return flags & 5  # read or write

        # TODO 4 is MP_STREAM_CLOSE

        return -1  # Other requests are unsupported

    async def put_in(self, buf: bytes | memoryview) -> Awaitable:
        "feed to read buffer"
        if main.user_task is not None and len(buf) == 1 and buf[0] == 3:
            main.user_task.cancel()
        await self._rb.write(buf)

    def start(self):
        "Start using this."
        if main.console is not None:
            raise RuntimeError("Already up")

        # if self._wb.n_avail < 100: self.write(b"Dup ")
        if self.cfg["keep"]:
            os.dupterm(self, 1)
        else:
            self._term = os.dupterm(self, 0)
        # if self._wb.n_avail < 100: self.write(b"Duped.\n")
        if self.cfg.get("repl", False):
            main.start(self)
        return self

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
        print("Console Setup", self.cfg, file=sys.stderr)
        self.cons = await AC_use(self, Console(self.cfg))

    doc_r = dict(_d="Read console data", _0="int:maxlength (default 32)")

    async def cmd_r(self, n: int = 32) -> bytes:
        "read from stdout/stderr"
        buf = bytearray(n)
        res = await self.cons.get_out(buf)
        if not res:
            buf = b""
        elif res < n:
            buf = memoryview(buf)[:res]
        return buf

    doc_w = dict(_d="Write console data", _0="bytes: data")

    async def cmd_w(self, data: bytes):
        "write stdin"
        await self.cons.put_in(data)

    doc_rw = dict(
        _d="r/w console byte stream",
        _0="int:rdbuflen (64)",
        _i="bytes:for stdin",
        _o="bytes:from stdout+stderr",
    )

    async def stream_rw(self, msg):
        "read/write the console stream"
        n = msg.get(0, 32)
        async with msg.stream() as st, TaskGroup() as tg:

            @tg.start_soon
            async def rd():
                while True:
                    await st.send(await self.cmd_r(n))

            async for m in st:
                await self.cmd_w(m[0])
            tg.cancel()

    doc_rb = dict(_d="Read input buffer", _0="int:maxlength (default 32)")

    async def stream_rb(self, msg: Msg):
        "read from stdin"
        buf = bytearray(msg.get(0, 32))
        if msg.can_stream:
            async with msg.stream_w() as ms:
                while True:
                    res = await self.cons.readinto(buf)
                    await ms.send(buf[:res])
        else:
            res = await self.cons.readinto(buf)
            if not res:
                buf = b""
            else:
                buf = memoryview(buf)[:res]
            await msg.result(buf)
