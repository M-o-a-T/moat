"""
This class implements the basic infrastructure to run an RPC system via an
unreliable, possibly-reordering, and/or stream-based transport

We have a stack of classes. The "link" chain leads from the command handler
to the actual hardware, represented by some Stream subclass.

Everything is fully asynchronous and controlled by the MoaT stack.
There are no callbacks from a linked-to module back to its user.
Opening a link is equivalent to entering its async context.

The "wrap" method provides a secondary context that can be used for
a persistent outer context, e.g. to hold a listening socket.

Methods for sending data typically return when the data has been sent. The
exception is the `Reliable` module, which limits this to commands.
"""

from __future__ import annotations

from moat.lib.cmd.const import B_FLAGSTR
from moat.lib.cmd.stream import wire2i_f
from moat.util.compat import ACM, AC_exit, AC_use, log

# Typing

from typing import TYPE_CHECKING  # isort:skip

if TYPE_CHECKING:
    from contextlib import AbstractAsyncContextManager

    from collections.abc import Awaitable
    from typing import Any, Buffer


class _NullCtx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *tb):
        pass


_nullctx = _NullCtx()


class Base:
    """
    The MoaT stream base class for "something connected".

    This class *must* be used as an async context manager.

    Usage:

    Use the `AC_use` helper if you need to call an async context manager or
    to register a destructor.

    Augment `setup` or `teardown` to add non-stream related features.

    Override `wrap` to return an async context manager that holds resources
    which must survive reconnection, e.g. a MQTT link's persistent state or
    a listening socket.
    """

    s = None

    def __init__(self, cfg):
        self.cfg = cfg

    def wrap(self) -> AbstractAsyncContextManager:
        """
        Async context manager for holding a cross-connection context.

        By default does nothing.
        """
        return _nullctx

    async def __aenter__(self):
        await ACM(self)(self.teardown)
        try:
            await self.setup()
            return self
        except BaseException as exc:
            await AC_exit(self, type(exc), exc, getattr(exc, "__traceback__", None))
            raise

    def __aexit__(self, *tb) -> Awaitable:
        return AC_exit(self, *tb)

    async def setup(self):
        """
        Basic async setup.

        Call first when overriding.
        """

    async def teardown(self):
        """
        Object destructor.

        Should not fail when called with a partially-created object.
        """


class BaseConn(Base):
    """
    The MoaT stream base class for "something connected that talks".

    This class *must* be used as an async context manager.

    Usage:

    Override `stream` to create the data link. Use `AC_use` to
    call an async context manager or to register a destructor.

    Augment `setup` or `teardown` to add non-stream related features.
    """

    s = None

    async def setup(self):
        """
        Object construction.

        By default, assigns the result of calling `stream` to the attribute
        ``s``.
        """
        if self.s is not None:
            raise RuntimeError("Busy!")

        self.s = await self.stream()

    async def teardown(self):
        """
        Object destructor.

        Should not fail when called with a partially-created object.
        """
        self.s = None

    async def stream(self):
        """
        Data stream setup.

        You need to use `AC_use` for setting up an async context
        or to register a cleanup handler.
        """
        raise NotImplementedError(f"'stream' in {self!r}")


class BaseMsg(BaseConn):
    """
    A stream base module for messages. May not be useful.

    Implement send/recv.
    """

    async def send(self, m: Any) -> Any:
        """
        Send a message.
        """
        raise NotImplementedError(f"'send' in {self!r}")

    async def recv(self) -> Any:
        """
        Receive a message.
        """
        raise NotImplementedError(f"'recv' in {self!r}")


class BaseBlk(BaseConn):
    """
    A stream base module for bytestrings. May not be useful.

    Implement snd/rcv.
    """

    async def snd(self, m: Buffer | bytes) -> None:
        """
        Send a block of bytes.
        """
        raise NotImplementedError(f"'send' in {self!r}")

    async def rcv(self) -> Buffer | bytes:
        """
        Receive a block of bytes.
        """
        raise NotImplementedError(f"'recv' in {self!r}")


class BaseBuf(BaseConn):
    """
    A stream base module for bytestreams.

    Implement rd/wr.
    """

    async def rd(self, buf: Buffer) -> int:
        """
        Read some bytes.

        @buf is a bytearray to read data into. The return value is the
        number of bytes filled.

        This method never returns zero. End-of-file raises `EOFError`.
        """
        raise NotImplementedError(f"'rd' in {self!r}")

    async def wr(self, buf: Buffer | bytes) -> int:
        """
        Write some bytes.
        """
        raise NotImplementedError(f"'wr' in {self!r}")


class StackedConn(BaseConn):
    """
    Base class for connection stacking.

    Connection stacks have a lower layer. `stream` generates a new
    connection from it, using its async context manager.
    stores the result in the attribute ``par`.`
    """

    link = None

    def __init__(self, link, cfg):
        super().__init__(cfg=cfg)
        self.link = link

    def wrap(self):  # noqa:D102
        return self.link.wrap()

    def stream(self):  # async
        """
        Generate the low-level connection this module uses.

        By default, returns the linked stream's async context.
        """
        return AC_use(self, self.link)


class StackedMsg(StackedConn, BaseMsg):
    """
    A no-op stack module for messages. Override to implement interesting features.

    Use the attribute "s" to store the linked stream's context.
    """

    def send(self, m):  # async
        "Send. Transmits a structured message"
        return self.s.send(m)

    def recv(self):  # async
        "Receive. Returns a message."
        return self.s.recv()

    def cwr(self, buf):  # async
        "Console Send. Returns when the buffer is transmitted."
        return self.s.cwr(buf)

    def crd(self, buf) -> len:  # async
        "Console Receive. Returns data by reading into a buffer."
        return self.s.crd(buf)


class StackedBuf(StackedConn, BaseBuf):
    """
    A no-op stack module for byte steams. Override to implement interesting features.

    Use the attribute "s" to store the linked stream's context.
    """

    def wr(self, buf):  # async
        "Send. Returns when the buffer is transmitted."
        return self.s.wr(buf)

    def rd(self, buf) -> len:  # async
        "Receive. Returns data by reading into a buffer."
        return self.s.rd(buf)


class StackedBlk(StackedConn, BaseBlk):
    """
    A no-op stack module for bytestrings. Override to implement interesting features.

    Use the attribute "s" to store the linked stream's context.
    """

    cwr = StackedMsg.cwr
    crd = StackedMsg.crd

    def snd(self, m):  # async
        "Send. Transmits a structured message"
        return self.s.send(m)

    def rcv(self):  # async
        "Receive. Returns a message."
        return self.s.rcv()


class LogMsg(StackedMsg, StackedBuf, StackedBlk):
    """
    Log whatever messages cross this stack.

    This implements all of StackedMsg/Buf/Blk.
    """

    # StackedMsg is first because MicroPython uses only the first class and
    # we get `cwr` and `crd` that way.

    def __init__(self, link, cfg):
        super().__init__(link, cfg)
        self.txt = cfg.get("txt", "S")

    async def setup(self):  # noqa:D102
        log("X:%s start", self.txt)
        await super().setup()

    async def teardown(self):  # noqa:D102
        log("X:%s stop", self.txt)
        await super().teardown()

    def _repr(self, m, sub=None):
        if not isinstance(m, dict):
            return repr(m)
        res = []
        for k, v in m.items():
            if sub == k:
                res.append(f"{k}={self._repr(v)}")
            else:
                res.append(f"{k}={v!r}")
        return "{" + " ".join(res) + "}"

    def _repr_bang(self, m):
        m = m[:]
        i, fl = wire2i_f(m.pop(0))
        f = B_FLAGSTR[fl]
        if i >= 0:
            f += "+"
        f += str(i)
        return f, self._repr(m)

    async def send(self, m):  # noqa:D102
        if self.txt[0] == "!" and isinstance(m, (list, tuple)) and m and isinstance(m[0], int):
            log("S:%s %s %s", self.txt, *self._repr_bang(m))
        else:
            log("S:%s %s", self.txt, self._repr(m, "d"))
        try:
            res = await self.s.send(m)
        except BaseException as exc:
            log("S:%s stop %r", self.txt, exc)
            raise
        else:
            log("S:%s =%s", self.txt, self._repr(res, "d"))
            return res

    async def recv(self):  # noqa:D102
        log("R:%s", self.txt)
        try:
            msg = await self.s.recv()
        except BaseException as exc:
            log("R:%s stop %r", self.txt, exc)
            raise
        else:
            log("R:%s %s", self.txt, self._repr(msg, "d"))
            return msg

    async def snd(self, m):  # noqa:D102
        log("SB:%s %r", self.txt, repr_b(m))
        try:
            return await self.s.snd(m)
        except BaseException as exc:
            log("SB:%s stop %r", self.txt, exc)
            raise

    async def rcv(self):  # noqa:D102
        log("RB:%s", self.txt)
        try:
            msg = await self.s.rcv()
        except BaseException as exc:
            log("RB:%s stop %r", self.txt, exc)
            raise
        else:
            log("RB:%s %r", self.txt, repr_b(msg))
            return msg

    async def wr(self, buf):  # noqa:D102
        log("S:%s %r", self.txt, repr_b(buf))
        try:
            res = await self.s.wr(buf)
        except BaseException as exc:
            log("S:%s stop %r", self.txt, exc)
            raise
        else:
            log("S:%s =%r", self.txt, res)
            return res

    async def rd(self, buf) -> len:  # noqa:D102
        log("R:%s %d", self.txt, len(buf))
        try:
            res = await self.s.rd(buf)
        except BaseException as exc:
            log("R:%s stop %r", self.txt, exc)
            raise
        else:
            log("R:%s %r", self.txt, repr_b(buf[:res]))
            return res

    async def cwr(self, buf):  # noqa:D102
        log("SC:%s %r", self.txt, repr_b(buf))
        try:
            res = await self.s.cwr(buf)
        except BaseException as exc:
            log("SC:%s stop %r", self.txt, exc)
            raise
        else:
            log("SC:%s =%r", self.txt, res)
            return res

    async def crd(self, buf) -> len:  # noqa:D102
        log("RC:%s %d", self.txt, len(buf))
        try:
            res = await self.s.crd(buf)
        except BaseException as exc:
            log("RC:%s stop %r", self.txt, exc)
            raise
        else:
            log("RC:%s %r", self.txt, repr_b(buf[:res]))
            return res


def repr_b(b):
    "show bytearray and memoryview as bytes"
    if isinstance(b, bytes):
        return b
    return bytes(b)


LogBuf = LogMsg
LogBlk = LogMsg
