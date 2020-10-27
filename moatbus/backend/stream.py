#
"""
Send bus messages to a Trio stream
"""

import trio
from trio.abc import Stream
from contextlib import asynccontextmanager

from . import BaseBusHandler
from ..serial import SerBus
from ..util import CtxObj
from weakref import ref


class _Bus(SerBus):
    def __init__(self, stream):
        self.stream = ref(stream)
        super().__init__()

    def report_error(self, typ, **kw):
        self.stream()._report_error(typ)

    def set_timeout(self, flag):
        self.stream()._set_timeout(flag)
    
    def data_out(self, bits):
        self.stream()._data_out(bits)
    
    def process(self, msg):
        self.stream()._process(msg)

    def process_ack(self):
        self.stream()._process_ack()


class Anyio2TrioStream:
    """
    Wrapping an anyio stream so that it behaves like a Trio stream.
    """
    def __init__(self, stream):
        self._stream = stream
    async def receive_some(self, max_bytes=None):
        if max_bytes is None:
            max_bytes=65535
        return await self._stream.receive(max_bytes=max_bytes)
    async def send_all(self, data):
        await self._stream.send(data)
    async def aclose(self):
        await self._stream.aclose()

class StreamBusHandler(BaseBusHandler, CtxObj):
    """
    This class defines the interface for exchanging MoaT messages on any
    Trio stream.

    Usage::
        
        async with StreamBusHandler(stream,0.05) as bus:
            async for msg in bus:
                await bus.send(another_msg)
    """



    def __init__(self, stream:Stream, name=None, tick:float = 0.1):
        super().__init__(name)
        self._bus = _Bus(self)
        self._stream = stream
        self._wq_w,self._wq_r = trio.open_memory_channel(150)
        self._rq_w,self._rq_r = trio.open_memory_channel(1500)
        self.errors = dict()
        self._timeout_evt = trio.Event()
        self._timeout_tick = tick

    @asynccontextmanager
    async def _ctx(self):
        async with trio.open_nursery() as n:
            await n.start(self._read, n)
            await n.start(self._write)
            await n.start(self._timeout)
            try:
                yield self
            finally:
                n.cancel_scope.cancel()


    async def _timeout(self, task_status=trio.TASK_STATUS_IGNORED):
        task_status.started()
        while True:
            await self._timeout_evt.wait()
            await trio.sleep(self._timeout_tick)
            if self._timeout_evt.is_set():
                self._bus.timeout()


    async def _read(self, n, task_status=trio.TASK_STATUS_IGNORED):
        task_status.started()
        async for m in self._stream:
            for b in m:
                self._bus.char_in(b)
        n.cancel_scope.cancel()


    async def _write(self, task_status=trio.TASK_STATUS_IGNORED):
        task_status.started()
        async for data in self._wq_r:
            await self._stream.send_all(data)


    async def send(self, msg, prio=0):
        self._bus.send(msg, prio)

    def __aiter__(self):
        return self

    def __anext__(self):  # async
        return self._rq_r.receive()

    def _report_error(self, typ, **kw):
        print("Err",repr(typ))
        self.errors[typ] = 1+self.errors.get(typ,0)

    def _set_timeout(self, flag):
        if self._timeout_evt.is_set():
            if not flag:
                self._timeout_evt = trio.Event()
        else:
            if flag:
                self._timeout_evt.set()
    
    def _process(self, msg):
        self._rq_w.send_nowait(msg)

    def _data_out(self, data):
        self._wq_w.send_nowait(data)

    def _process_ack(self):
        pass

