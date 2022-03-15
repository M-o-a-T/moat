#
"""
Send bus messages to an AnyIO stream
"""

import anyio
from anyio.abc import AnyByteStream
from contextlib import asynccontextmanager

from . import BaseBusHandler
from ..serial import SerBus
from weakref import ref


class _Bus(SerBus):
    def __init__(self, stream):
        self.stream = ref(stream)
        super().__init__()

    def report_error(self, typ, **kw):
        self.stream()._report_error(typ, **kw)

    def set_timeout(self, flag):
        self.stream()._set_timeout(flag)
    
    def data_out(self, bits):
        self.stream()._data_out(bits)
    
    def process(self, msg):
        self.stream()._process(msg)

    def process_ack(self):
        self.stream()._process_ack()


class StreamHandler(BaseBusHandler):
    """
    This class defines the interface for exchanging MoaT messages on any
    AnyIO stream.

    Usage::
        
        async with StreamBusHandler(stream,0.05) as bus:
            async for msg in bus:
                await bus.send(another_msg)
    """

    def __init__(self, client, stream:AnyByteStream, tick:float = 0.1):
        # Subclasses may pass `None` as Stream, and set `._stream` before
        # calling `_ctx`.

        super().__init__(client)
        self._bus = _Bus(self)
        self._stream = stream
        self._wq_w,self._wq_r = anyio.create_memory_object_stream(150)
        self._rq_w,self._rq_r = anyio.create_memory_object_stream(1500)
        self.errors = dict()
        self._timeout_evt = anyio.create_event()
        self._timeout_tick = tick

    @asynccontextmanager
    async def _ctx(self):
        async with anyio.create_task_group() as n:
            await n.spawn(self._read, n)
            await n.spawn(self._write)
            await n.spawn(self._timeout)
            try:
                yield self
            finally:
                await n.cancel_scope.cancel()


    async def _timeout(self):
        while True:
            await self._timeout_evt.wait()
            await anyio.sleep(self._timeout_tick)
            if self._timeout_evt.is_set():
                self._bus.timeout()


    async def _read(self, n):
        async for m in self._stream:
            for b in m:
                self._bus.char_in(b)
        n.cancel_scope.cancel()


    async def _write(self):
        async for data in self._wq_r:
            await self._stream.send(data)


    async def send(self, msg):
        self._bus.send(msg)

    def __aiter__(self):
        return self

    def __anext__(self):  # async
        return self._rq_r.receive()

    def _report_error(self, typ, **kw):
        print("Err",repr(typ),kw)
        self.errors[typ] = 1+self.errors.get(typ,0)

    def _set_timeout(self, flag):
        if self._timeout_evt.is_set():
            if not flag:
                self._timeout_evt = anyio.create_event()
        else:
            if flag:
                self._timeout_evt.set()
    
    def _process(self, msg):
        self._rq_w.send_nowait(msg)

    def _data_out(self, data):
        self._wq_w.send_nowait(data)

    def _process_ack(self):
        pass

