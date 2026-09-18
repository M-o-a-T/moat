"""
Basic handler for iterating incoming Moat connections.
"""

from __future__ import annotations

from moat.util import Queue
from moat.lib.micro import ACM, AC_exit, AC_use, Event, L, TaskGroup
from moat.lib.stream import BaseConn

# typing
from typing import TYPE_CHECKING  # isort:skip

if TYPE_CHECKING:
    from types import TracebackType

    from moat.lib.stream.base import Buffer, MutBuffer

    from collections.abc import Awaitable
    from typing import Never


class BaseConnIter:
    """
    Iterate incoming connections.

    You need to override the "accept" method.

    Subclasses set ``port`` to the actual listening port in their
    ``__init__`` and update it after binding when ``port=0`` was used.
    """

    port: int | None = None
    """The port this listener is bound to.

    Initially ``None``; after binding it holds the actual (possibly
    OS-assigned) port number.
    """

    def __init__(self):
        self.q = Queue(1)
        self.evt = Event()
        self._port_ready = Event()

    async def __aenter__(self):
        self.tg = await ACM(self)(TaskGroup())
        try:
            self.tg.start_soon(self.accept)
            if self.port is None or self.port == 0:
                await self._port_ready.wait()
            return self
        except BaseException as exc:
            await AC_exit(self, type(exc), exc, getattr(exc, "__traceback__", None))
            raise

    def _port_assigned(self) -> None:
        """Called by accept() after the port is bound."""
        self._port_ready.set()

    async def __aexit__(self, *exc):
        await AC_exit(self, *exc)

    if L:

        def set_ready(self) -> None:
            "signals that the socket-or-whatever accepts connections"
            self.evt.set()

        def is_ready(self) -> Awaitable:
            "wait for the socket-or-whatever to accept connections"
            return self.evt.wait()

    def add_conn(self, c: BaseConn) -> Awaitable:
        "queues the connection for starting a task"
        return self.q.put(c)

    async def accept(self) -> Never:
        """
        Background task to accept incoming connections.

        Call ``await self.add_conn(conn)`` for each connection.

        Call ``self.ready()`` as soon as the socket-or-whatever is ready to accept links.
        """
        raise NotImplementedError

    def __aiter__(self):
        return self

    def __anext__(self) -> Awaitable[BaseConn]:
        return self.q.get()


class ListenerLink(BaseConn):
    """
    Adapter that presents a :class:`BaseConnIter` as a reconnectable stream.

    Each time this stream is (re-)entered as an async context manager, it
    pulls the next incoming connection from the underlying :class:`BaseConnIter`
    and delegates I/O to it.

    This allows a :class:`~moat.lib.stream.ReliableMsg` layer (or any other
    stacked stream) to sit *above* the listener and transparently reconnect
    when the underlying transport disappears.

    The class provides ``rd``/``wr`` (for :func:`~moat.lib.stream.serial_stack`)
    and ``snd``/``rcv`` (for :func:`~moat.lib.stream.ws_stack`) by delegating
    to the current connection.  The appropriate set of methods is used
    depending on the stream stack built on top.

    Args:
        listener: A :class:`BaseConnIter` subclass.
    """

    listener: BaseConnIter

    def __init__(self, listener: BaseConnIter):
        super().__init__()
        self.listener = listener

    async def __aenter__(self):
        await self.listener.__aenter__()
        return await super().__aenter__()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool | None:
        try:
            return await super().__aexit__(exc_type, exc, tb)
        finally:
            await self.listener.__aexit__(exc_type, exc, tb)

    async def stream(self):
        """Return the next incoming connection."""
        conn = await self.listener.__anext__()
        await AC_use(self, conn)
        return conn

    # -- BaseBuf delegation (for serial_stack) --

    async def rd(self, buf: MutBuffer) -> int:
        """Read data from the current connection."""
        if self.s is None:
            raise EOFError
        return await self.s.rd(buf)

    async def wr(self, data: Buffer) -> int:
        """Write data to the current connection."""
        if self.s is None:
            raise EOFError
        return await self.s.wr(data)

    # -- BaseBlk delegation (for ws_stack) --

    async def snd(self, m: Buffer) -> None:
        """Send a block via the current connection."""
        if self.s is None:
            raise EOFError
        await self.s.snd(m)

    async def rcv(self) -> Buffer:
        """Receive a block from the current connection."""
        if self.s is None:
            raise EOFError
        return await self.s.rcv()

    # -- Console delegation (crd/cwr) --

    async def crd(self, buf: MutBuffer) -> int:
        """Read console data from the current connection."""
        if self.s is None:
            raise EOFError
        return await self.s.crd(buf)

    async def cwr(self, buf: Buffer) -> None:
        """Write console data to the current connection."""
        if self.s is None:
            raise EOFError
        await self.s.cwr(buf)
