from .compat import Event,ticks_ms,ticks_add,ticks_diff,wait_for_ms,print_exc,CancelledError,TaskGroup, idle
from contextlib import asynccontextmanager

from serialpacker import SerialPacker
from msgpack import Packer,Unpacker, OutOfData
from pprint import pformat

import uasyncio
from uasyncio import core
from uasyncio import Lock
from uasyncio.stream import Stream

import logging
logger = logging.getLogger(__name__)

from . import _Stacked


class _Base(_Stacked):
    def __init__(self, stream):
        super().__init__(None)
        self.s = stream

#class _Console(_Base):
#    # handle non-packetized data
#    # dispatch packetized data
#    def __init__(self, *a,**k):
#        super().__init__(*a,**k)
#        self.buf = bytearray()
#
#    async def stream_in(self, b):
#        # console data stream, i.e. anything not packetized
#        if b[0] in (3,4):
#            raise Keyboardinterrupt()
#        elif b[-1] != 0x0A:
#            self.buf.extend(b)
#        elif self.buf:
#            try:
#                res = eval(self.buf.decode("utf-8"))
#            except Exception as exc:
#                print_exc(exc)
#                res = str(exc)
#            await self.send(res)
#            self.buf = bytearray()
#        else:
#            await self.send(None)
#
#
#    async def dispatch(self, msg):
#        try:
#            await self.spawn(self.child.dispatch, msg)
#        except Exception as exc:
#            print(f"Processing {msg} to {res}")
#            print_exc(exc)
#

class MsgpackStream(_Base):
    # structured messages > MsgPack bytestream
    #
    # Use this if your stream is reliable (TCP, USB, …)

    def __init__(self, stream, **kw):
        super().__init__(stream)
        self.unpacker = Unpacker(stream, **kw)
        self.pack = Packer().packb

    async def send(self, msg):
        await super().send(self.pack(msg))

    async def recv(self):
        return await self.unpacker.unpack()


class MsgpackHandler(_Stacked):
    # structured messages > chunked bytestrings

    def __init__(self, stream, **kw):
        super().__init__(stream)
        self.unpacker = Unpacker(stream, **kw).unpackb
        self.pack = Packer().packb

    async def send(self, msg):
        await super().send(self.pack(msg))

    async def recv(self):
        m = await self.parent.recv()
        return self.unpacker(m)


class SerialPackerStream(_Base):
    # chunked bytestrings > SerialPacker messages
    #
    # Use this (and a MsgpackHandler and a Reliable) if your stream
    # is unreliable (TTL serial).

    def __init__(self, stream, **kw):
        super().__init__(None)

        self.s = stream
        self.p = SerialPacker(**kw)
        self.buf = bytearray(16)
        self.i = 0
        self.n = 0

    async def recv(self):
        while True:
            while self.i < self.n:
                msg = self.p.feed(c[self.i])
                self.i += 1
                if msg is not None:
                    return msg

            n = await self.s.readinto(buf)
            if not n:
                raise EOFError
            self.i = 0
            self.n = n


    async def send(self, msg):
        h,t = self.p.frame(msg)
        await self.s.write(h+msg+t)


class AsyncStream(Stream):
    # convert a sync stream to an async one
    # reads a byte at a time if no any()
    # does timed-out short reads

    def __init__(self, s, **kw):
        super().__init__(s, **kw)

        def one():
            return 1
        self._any = getattr(stream, "any", one)
        self._wlock = Lock()

    async def readinto(self, buf, timeout=100):
        i = 0
        m = memoryview(buf)
        while i < n:
            if i==0 or timeout<0:
                await core._io_queue.queue_read(self.s)
            else:
                try:
                    await wait_for_ms(timeout, core._io_queue.queue_read, self.s)
                except TimeoutError:
                    break
            d = self.s.readinto(buf[i:i+min(self._any(),n-i)])
            i += d
        return i

    async def read(self, n, timeout=100):
        buf = bytearray(n)
        i = self.readinto(buf, timeout)
        if i < n:
            return buf[0:i]
        return buf

    async def readexactly(self, n):
        buf = bytearray(n)
        return await self.readinto(buf,timeout=-1)

    async def write(self, buf):
        # no we do not use a sync "write" plus an async "drain".
        async with self._wlock:
            m = memoryview(buf)
            i = 0
            while i < len(buf):
                await core._io_queue.queue_write(self.s)
                n = self.s.write(m[i:])
                if n:
                    i += n
            return i

