from __future__ import annotations

from moat.util import Queue, CtxObj, NotGiven, QueueFull
from moat.micro.compat import TaskGroup
from contextlib import asynccontextmanager

try:
    from anyio import Event
except ImportError:
    from asyncio import Event

import logging
logger = logging.getLogger(__name__)


class LinkDown(RuntimeError):
    pass

class StreamError(RuntimeError):
    pass

from typing import TYPE_CHECKING  # isort:skip

if TYPE_CHECKING:
    from typing import Awaitable


class CmdHandler(CtxObj):
    """
    This is a manager for multiplexed command/response interactions between
    two peers.

    All such interactions are independent of each other and may contain
    data streams.
    """
    def __init__(self):
        self.c_in: dict[int,Msg] = {}
        self.c_out: dict[int,Msg] = {}
        self._id = 0
        self._send_q = Queue(9)
        self._recv_q = Queue(99)

    def _gen_id(self):
        # Generate the next free ID.
        # TODO
        i = self._id
        while i < 6:
            if i not in self.c_out:
                self._id = i
                return i
            i += 1
        while i in self.c_out:
            i += 1
        self._id = i
        return i

    def stream_r(self, *data, **kw) -> AsyncContextManager[Msg]:
        return self._stream(data,kw,True,False)

    def stream_w(self, *data, **kw) -> AsyncContextManager[Msg]:
        return self._stream(data,kw,False,True)

    def stream_rw(self, *data, **kw) -> AsyncContextManager[Msg]:
        return self._stream(data,kw,True,True)

    def cmd_in(self) -> Awaitable[Msg]:
        """Retrieve new incoming commands"""
        return self._recv_q.get()

    async def cmd(self, *d, **kw):
        """Send a simple command, receive a simple reply."""
        i = self._gen_id()
        self.c_out[i] = c = Msg(self, i)
        c.stream_in = NotGiven
        await self._send(i<<2, d, kw)
        try:
            await c.cmd_in.wait()
            return c.cmd
        finally:
            del self.c_out[i]

        await self._send()

    async def dispatch(self, cb):
        async def _disp(msg):
            err = False
            i = -1-(msg.i>>2)
            try:
                res = await cb(msg)
            except AssertionError:
                raise
            except Exception as exc:
                if msg.stream_out is False:
                    logger.error("Error not sent (msg=%r)", msg, exc_info=exc)
                    return
                err = True
                res = (exc.__class__.__name__, exc.args)
            finally:
                del self.c_in[i]

            if msg.stream_out is not False:
                if err and msg.stream_out is False:
                    self._log("Error suppressed: %r", res)
                    err = False
                else:
                    await msg.send(res, err=err)


        while True:
            msg = await self._recv_q.get()
            self._tg.start_soon(_disp, msg)
            


    @asynccontextmanager
    async def _stream(self, d,kw,sin,sout):
        i = self._gen_id()
        self.c_out[i] = c = Msg(self, i)
        c.stream_in = sin
        c.stream_out = out
        try:
            await self._send(i<<2+bool(sout), data, kw)
            d = await c.recv_q.get()
        finally:
            del self.c_out[i]

    def _send(self, i, data, kw):
        return self._send_q.put((i, data, kw))

    async def msg_out(self):
        i,d,kw = await self._send_q.get()
        # this is somewhat inefficient but oh well
        if kw or (d and isinstance(d[-1], dict)):
            return (i,)+tuple(d)+(kw,)
        else:
            return (i,)+tuple(d)

    async def msg_in(self, msg):
        i = msg[0]
        stream = i&1
        error = i&2
        i >>= 2
        if i < 0:
            i = -1-i
            try:
                conv = self.c_out[i]
            except KeyError:
                self._debug("Spurious message", msg)
                return
        else:
            if i not in self.c_in:
                self.c_in[i] = conv = Msg(self, -1-i, )
                self._recv_q.put_nowait(conv)
                # may propagate QueueFullError, which is intentional
            else:
                conv = self.c_in[i]
        await conv._recv(msg)


    @asynccontextmanager
    async def _ctx(self):
        async with TaskGroup() as tg:
            self._tg = tg
            try:
                yield self
            finally:
                for conv in self.c_out.values():
                    conv.kill()
                for conv in self.c_in.values():
                    conv.kill()
                tg.cancel()
        self.c_in = {}
        self.c_out = {}


class Msg:
    """
    This object handles one conversation.
    It's also used as a message container.
    """
    def __init__(self, parent:CmdHandler, i:int):
        self.parent = parent
        self.i = i<<2  # ready for sending
        self.stream_out: bool|None = None  # None if we never sent
        self.stream_in: bool|None= None  # None if never received, NotGiven if unwanted
        self.cmd: list[Any] = None
        self.cmd_in:Event = Event()
        self.cmd2 = None
        self.data = {}

        self.recv_q = Queue(99)

    def kill(self):
        self.parent = None
        try:
            self.recv_q.put_nowait_error(LinkDown())
        except QueueFull:
            self.recv_q = LinkDown()
        except Exception as exc:
            logger.error("Shutting down: %r", exc)

    async def _recv(self, msg):
        stream = msg[0]&1
        err = msg[0]&2
        msg = msg[1:]
        if self.cmd is None or not stream:
            if self.cmd is None:
                if isinstance(msg[-1], dict):
                    self.data = msg[-1]
                    msg = msg[:-1]
                self.cmd = msg
                self.cmd_in.set()
            else:
                # this can happen when the stream ends
                # before the reader starts to retrieve data
                assert not stream
                self.cmd2 = msg
        if stream:
            if self.stream_in is NotGiven:
                # reject: we don't accept incoming streams
                self.stream_in = False
                await self._send([-2],{},err=True)
            elif self.stream_in is None:
                self.stream_in = True
            elif self.stream_in:
                if err:
                    self.recv_q.put_nowait_error(StreamError(msg))
                else:
                    self.recv_q.put_nowait(msg)
        else:
            if self.stream_in is not False:
                self.recv_q.close_sender()
            self.stream_in = False

    async def _send(self, d,kw, stream=False, err=False) -> None:
        if stream is None:
            stream = bool(self.stream_out)
        if self.stream_out is False:
            if self.stream_in and err and not stream:
                stream = True
                # special case to kill an incoming stream
            else:
                raise RuntimeError("already replied")
        else:
            self.stream_out = stream
        await self.parent._send(self.i|bool(stream)|(bool(err)<<1), d,kw)

    def send(self, *a, **kw) -> Awaitable[None]:
        """
        Send a reply.
        Transmissions are auto-marked as belonging to the stream during streaming.
        """
        return self._send(a, kw, stream=None)

    def send_error(self, *a, **kw) -> Awaitable[None]:
        return self._send(d, kw, stream=None, err=True)

    async def stop(self):
        """stops an incoming stream"""
        if not self.stream_in:
            return
        i = self.i|2
        if self.stream_out is False:
            i|= 1
        await self.parent._send

    def stream_r(self, *data, **kw) -> AsyncContextManager[Msg]:
        return self._stream(data,kw,True,False)

    def stream_w(self, *data, **kw) -> AsyncContextManager[Msg]:
        return self._stream(data,kw,False,True)

    def stream_rw(self, *data, **kw) -> AsyncContextManager[Msg]:
        return self._stream(data,kw,True,True)

    @asynccontextmanager
    async def _stream(self, d,kw,sin,sout):
        if self.stream_out is not None:
            raise RuntimeError("Stream-out already set")
        self.stream_out = sout
        self.cmd = None
        self.cmd_in = Event()
        if self.cmd2 is not None:
            self.cmd, self.cmd2 = self.cmd2, None
            self.cmd_in.set()

        await self._send(d,kw, stream=sout)
        yield self
        pass # an end message must be sent, but ours is not the place


    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._recv_q is None:
            raise StopAsyncIteration
        return await self._recv_q.get()


