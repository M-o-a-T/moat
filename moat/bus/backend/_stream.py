#
"""
Send bus messages to an AnyIO stream
"""

from __future__ import annotations

import anyio
from contextlib import asynccontextmanager
from weakref import ref

from moat.bus.serial import SerBus

from . import BaseBusHandler

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from anyio.abc import AnyByteStream, TaskGroup
    from anyio.streams.memory import (
        MemoryObjectReceiveStream,
        MemoryObjectSendStream,
    )

    from moat.bus.message import BusMessage
    from moat.bus.serial import ERR


class _Bus(SerBus):
    _stream: ref[StreamHandler]

    def __init__(self, stream: StreamHandler) -> None:
        self._stream = ref(stream)
        super().__init__()

    def report_error(self, typ: ERR, **kw: Any) -> None:
        """Forward errors to the stream handler."""
        s = self._stream()
        if s is not None:
            s._report_error(typ, **kw)  # noqa:SLF001

    def set_timeout(self, flag: bool) -> None:
        """Forward timeout setting to the stream handler."""
        s = self._stream()
        if s is not None:
            s._set_timeout(flag)  # noqa:SLF001

    def data_out(self, data: bytes) -> None:
        """Forward outgoing data to the stream handler."""
        s = self._stream()
        if s is not None:
            s._data_out(data)  # noqa:SLF001

    def process(self, msg: BusMessage) -> None:
        """Forward received messages to the stream handler."""
        s = self._stream()
        if s is not None:
            s._process(msg)  # noqa:SLF001

    def process_ack(self) -> None:
        """Forward ACK to the stream handler."""
        s = self._stream()
        if s is not None:
            s._process_ack()  # noqa:SLF001


class StreamHandler(BaseBusHandler):
    """
    This class defines the interface for exchanging MoaT messages on any
    AnyIO stream.

    Usage::

        async with StreamBusHandler(stream,0.05) as bus:
            async for msg in bus:
                await bus.send(another_msg)
    """

    _bus: _Bus
    _stream: AnyByteStream | None
    _wq_w: MemoryObjectSendStream[bytes]
    _wq_r: MemoryObjectReceiveStream[bytes]
    _rq_w: MemoryObjectSendStream[BusMessage]
    _rq_r: MemoryObjectReceiveStream[BusMessage]
    errors: dict[Any, int]
    _timeout_evt: Any
    _timeout_tick: float

    def __init__(
        self, client: Any = None, stream: AnyByteStream | None = None, tick: float = 0.1
    ) -> None:
        # Subclasses may pass `None` as Stream, and set `._stream` before
        # calling `_ctx`.

        super().__init__(client)
        self._bus = _Bus(self)
        self._stream = stream
        self._wq_w, self._wq_r = anyio.create_memory_object_stream(150)
        self._rq_w, self._rq_r = anyio.create_memory_object_stream(1500)
        self.errors: dict[Any, int] = {}
        self._timeout_evt = anyio.Event()
        self._timeout_tick = tick

    @asynccontextmanager
    async def _ctx(self) -> Any:
        async with anyio.create_task_group() as n:
            n.start_soon(self._read, n)
            n.start_soon(self._write)
            n.start_soon(self._timeout)
            try:
                yield self
            finally:
                n.cancel_scope.cancel()

    async def _timeout(self) -> None:
        """Periodically trigger bus timeout processing."""
        while True:
            await self._timeout_evt.wait()
            await anyio.sleep(self._timeout_tick)
            if self._timeout_evt.is_set():
                self._bus.timeout()

    async def _read(self, n: TaskGroup) -> None:
        """Read from the stream and feed bytes to the bus."""
        assert self._stream is not None
        async for m in self._stream:
            for b in m:
                self._bus.char_in(b)
        n.cancel_scope.cancel()

    async def _write(self) -> None:
        """Write queued data to the stream."""
        assert self._stream is not None
        async for data in self._wq_r:
            await self._stream.send(data)

    async def send(self, msg: BusMessage) -> None:
        """Send a message via the bus."""
        self._bus.send(msg)

    def __aiter__(self) -> StreamHandler:
        return self

    async def __anext__(self) -> BusMessage:
        """Return the next received message."""
        return await self._rq_r.receive()

    def _report_error(self, typ: Any, **kw: Any) -> None:
        """Record a communication error."""
        print("Err", repr(typ), kw)
        self.errors[typ] = 1 + self.errors.get(typ, 0)

    def _set_timeout(self, flag: bool) -> None:
        """Set or clear the timeout event."""
        if self._timeout_evt.is_set():
            if not flag:
                self._timeout_evt = anyio.Event()
        else:
            if flag:
                self._timeout_evt.set()

    def _process(self, msg: BusMessage) -> None:
        """Queue a received message."""
        self._rq_w.send_nowait(msg)

    def _data_out(self, data: bytes) -> None:
        """Queue outgoing data."""
        self._wq_w.send_nowait(data)

    def _process_ack(self) -> None:
        """Handle an ACK (no-op)."""
        pass
