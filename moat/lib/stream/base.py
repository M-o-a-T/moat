"""
This package implements some basic infrastructure for handling data
streams in a structured manner. It contains three distinct classes:

- `BaseMsg` transports Python objects, using `send` and `recv`.
- `BaseBlk` transports delimited bytestrings, using `snd` and `rcv`.
- `BaseBuf` transports undelimited bytestrings, using `wr` and `rd`.

Additionally, message- and block-based classes understand `cwr` and `crd`
which transport out-of-band data. Typically these contain raw console bytes
that are interleaved with structured data; they are used on channels which
needs to multiplex both.

The common theme for using these classes is

- You assemble a communication stack bottom-up: start with a serial link;
  add packetizing, retransmission, and an object-codec.
- Using the top level as an async context managers establishes the complete
  stack; leaving the context tears it down.
- Most likely, connect the result to a [Base]MsgHandler.

Everything is fully asynchronous. There is no "new incoming data" callback:
it's the upper layer's job to repeatedly call the appropriate method to
read or receive new messages.

A `wrap` method provides a secondary context that can be used for
a persistent outer context, e.g. to keep a listening socket open.
"""

from __future__ import annotations

from moat.lib.micro import ACM, AC_exit, AC_use

# Typing

from typing import TYPE_CHECKING  # isort:skip

if TYPE_CHECKING:
    from contextlib import AbstractAsyncContextManager

    from collections.abc import Awaitable, Buffer
    from typing import Any


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

    Override `wrap` to contain an async context manager that holds resources
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
        Basic async setup method. You may use AC_exit.

        Call the superclass first, when overriding.
        """

    async def teardown(self):
        """
        Object destructor.

        Should not fail when called with a partially-created object.
        """


class BaseConn(Base):
    """
    This is the MoaT stream base class for "something connected that talks".

    This class *must* be used as an async context manager.

    Usage:

    Override `stream` to create the data link. Use `AC_use` to
    call an async context manager or to register a destructor.

    Augment `setup` or `teardown` to add non-stream related features.
    """

    s: Any = None

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

    async def wr(self, data: Buffer) -> int:
        """
        Write some bytes.
        """
        raise NotImplementedError(f"'wr' in {self!r}")


class StackedConn(BaseConn):
    """
    Base class for connection stacking.

    Connection stacks have a lower layer. Our `stream` methods uses it as an
    async context manager to create connection from it, using its

    Args:
        link(BaseConn): The lower layer to run on top of.
        cfg: Config data
    """

    link: BaseConn = None

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

    Args:
        link(BaseMsg): The lower layer to run on top of.
        cfg: Config data
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

    Args:
        link(BaseBuf): The lower layer to run on top of.
        cfg: Config data
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

    Args:
        link(BaseBlk): The lower layer to run on top of.
        cfg: Config data
    """

    cwr = StackedMsg.cwr
    crd = StackedMsg.crd

    def snd(self, m):  # async
        "Send. Transmits a structured message"
        return self.s.send(m)

    def rcv(self):  # async
        "Receive. Returns a message."
        return self.s.rcv()
