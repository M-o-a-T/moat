from __future__ import annotations

from moat.util import Queue, CtxObj, NotGiven, QueueFull
from moat.util.compat import TaskGroup, CancelScope
from contextlib import asynccontextmanager

try:
    from anyio import Event
except ImportError:
    from asyncio import Event

import logging
logger = logging.getLogger(__name__)

# bitfields

B_STREAM = 1
B_ERROR = 2

# errors

E_UNSPEC = -1
E_NO_STREAM = -2
E_CANCEL = -3
E_NOCMD = -4

class LinkDown(RuntimeError):
    pass

class StreamError(RuntimeError):
    pass

from typing import TYPE_CHECKING  # isort:skip

if TYPE_CHECKING:
    from typing import Awaitable

class _SA1:
    """
    shift a readonly list by 1. This is a minimal implementation, intended
    to avoid copying long-ish arrays.
    """
    def __new__(cls, a):
        if len(a) < 10:
            return a[1:]
        return object.__new__(cls,a)
    def __init__(self,a):
        self.a = a
    def __len__(self):
        return len(self.a)-1
    def __getitem__(self, i):
        if isinstance(i, slice):
            i=slice(
                    i.start if i.start<0 else i.start+1,
                    i.stop if i.stop<0 else i.stop+1,
                    i.end,
                    )
            return a[i]
        elif i >= 0:
            return self.a[i+1]
        elif i >= -len(self.a):
            return self.a[i]
        else:
            raise IndexError(i)
    def __repr__(self):
        return repr(self.a[1:])
    def __iter__(self):
        it = iter(self.a)
        next(it) # skip first
        return it


class CmdHandler(CtxObj):
    """
    This is a manager for multiplexed command/response interactions between
    two peers.

    All such interactions are independent of each other and may contain
    data streams.
    """
    def __init__(self, callback):
        self._in: dict[int,Msg] = {}
        self._out: dict[int,Msg] = {}
        self._id = 0
        self._send_q = Queue(9)
        self._recv_q = Queue(99)
        self._debug = logger.warning
        self._in_cb = callback

    def _gen_id(self):
        # Generate the next free ID.
        # TODO
        i = self._id
        while i < 6:
            if i not in self._out:
                self._id = i
                return i
            i += 1
        while i in self._out:
            i += 1
        self._id = i
        return i

    def cmd_in(self) -> Awaitable[Msg]:
        """Retrieve new incoming commands"""
        return self._recv_q.get()

    async def cmd(self, *d, **kw):
        """Send a simple command, receive a simple reply."""
        i = self._gen_id()
        self._out[i] = c = Msg(self, i)
        c.stream_in = NotGiven
        await self._send(i<<2, d, kw if kw else None)
        try:
            await c.cmd_in.wait()
            return c.msg
        except BaseException as exc:
            self._send_nowait((i<<2)|B_ERROR, [E_CANCEL])
            raise
        finally:
            del self._out[i]


    async def _handle(self, msg):
        async def _wrap(msg, task_status):
            async with CancelScope() as cs:
                msg.scope = cs
                task_status.started()
                err = ()
                res = NotGiven
                try:
                    res = await self._in_cb(msg)
                except AssertionError:
                    raise
                except Exception as exc:
                    if msg.stream_out is False:
                        logger.error("Error not sent (msg=%r)", msg, exc_info=exc)
                    else:
                        err = (exc.__class__.__name__, *exc.args)
                except BaseException as exc:
                    err = (E_CANCEL,)
                    raise
                finally:
                    # Handle termination.
                    if msg.stream_in is True:
                        msg.recv_q = None
                    else:
                        assert msg.id<0
                        del self._in[-1-msg.id]

                    # terminate outgoing stream, if any
                    if msg.stream_out is False:  # already sent
                        if res is not NotGiven:
                            self._debug("Result for %r suppressed: %r", msg, res)
                    elif err:
                        self._send_nowait(msg._i|B_ERROR, err)
                    else:
                        if not isinstance(res,(list,tuple)):
                            res = (res,)
                        await self._send(msg._i, res)

        await self._tg.start(_wrap, msg)
            

    def stream_r(self, *data, **kw) -> AsyncContextManager[Msg]:
        return self._stream(data,kw,True,False)

    def stream_w(self, *data, **kw) -> AsyncContextManager[Msg]:
        return self._stream(data,kw,False,True)

    def stream_rw(self, *data, **kw) -> AsyncContextManager[Msg]:
        return self._stream(data,kw,True,True)


    @asynccontextmanager
    async def _stream(self, d,kw,sin,sout):
        i = self._gen_id()
        self._out[i] = c = Msg(self, i)
        async with CancelScope() as cs:
            msg.scope = cs

            c.stream_in = sin
            c.stream_out = out
            try:
                await self._send(i<<2+bool(sout), data, kw)
                d = await c.recv_q.get()
            finally:
                if msg.stream_in is True:
                    msg.recv_q = None
                else:
                    del self._out[i]

    def _send(self, i, data, kw=None):
        return self._send_q.put((i, data, kw))

    def _send_nowait(self, i, data, kw=None):
        self._send_q.put_nowait((i, data, kw))

    async def msg_out(self):
        i,d,kw = await self._send_q.get()
        # this is somewhat inefficient but oh well
        if kw:
            return (i,)+tuple(d)+(kw,)
        else:
            return (i,)+tuple(d)

    async def msg_in(self, msg):
        i = msg[0]
        stream = i&B_STREAM
        error = i&B_ERROR
        i = -1-(i >> 2)
        if i < 0:
            ch = self._in
            idx = -1-i
        else:
            ch = self._out
            idx = i
        try:
            conv = ch[idx]
        except KeyError:
            if ch is self._out:
                self._debug("Spurious message %r", msg)
            elif ch is self._out:
                self._debug("Spurious error %r", msg)
            elif self._in_cb is None:
                self._send_nowait(((i<<2)&~B_STREAM)|B_ERROR, [E_NOCMD])
            else:
                ch[idx] = conv = Msg(self, i, msg=msg)
                await self._handle(conv)
            return
        try:
            await conv._recv(msg)
        except EOFError:
            del ch[i]


    @asynccontextmanager
    async def _ctx(self):
        async with TaskGroup() as tg:
            self._tg = tg
            try:
                yield self
            finally:
                for conv in self._out.values():
                    conv.kill()
                for conv in self._in.values():
                    conv.kill()
                tg.cancel()
        self._in = {}
        self._out = {}


class Msg:
    """
    This object handles one conversation.
    It's also used as a message container.

    The last non-streamed incoming message is available in @msg.
    The first item in the message is stored in @cmd, if the last item is a
    mapping it's in @data and individual keys can be accessed by indexing
    the message.
    """
    def __init__(self, parent:CmdHandler, i:int, msg:list|None = None):
        self.parent = parent
        self._i = i<<2  # ready for sending
        self.stream_out: bool|None = None  # None if we never sent
        self.stream_in: bool|None= None  # None if never received, NotGiven if unwanted
        self.cmd_in:Event = Event()
        self.msg2 = None

        self.msg:list = None
        self.cmd: Any = None  # first element of the message
        self.data:dict = {}  # last element, if dict

        self.recv_q = Queue(99)
        self.scope = None

        if msg is not None:
            self._set_msg(msg)

    def __getitem__(self, k):
        return self.data[k]

    def __contains__(self, k):
        return k in self.data

    def __repr__(self):
        r= f"<Msg:{self.id}"
        if self.stream_in is not False:
            r += " I"
            if self.stream_in is None:
                r += "?"
            elif self.stream_in is NotGiven:
                r += "-"
            elif self.stream_in is not True:
                r += repr(self.stream_in)
        if self.stream_out is not False:
            r += " O"
            if self.stream_in is None:
                r += "?"
            elif self.stream_out is not True:
                r += repr(self.stream_out)
        return r+">"

    @property
    def id(self):
        """
        This message's ID in human-readable form, avoiding zero
        so that when you examine log files, one sides has id=+3 and the
        other shows as -3
        """
        i = self._i >> 2
        if i >= 0:
            i += 1
        return i

    def kill(self):
        self.parent = None
        try:
            self.recv_q.put_nowait_error(LinkDown())
        except QueueFull:
            self.recv_q = LinkDown()
        except Exception as exc:
            logger.error("Shutting down: %r", exc)

    def _set_msg(self, msg):
        self.msg = _SA1(msg)
        self.cmd = msg[1]
        if isinstance(msg[-1], dict):
            self.data = msg[-1]
        else:
            self.data = None
        self.cmd_in.set()

    async def _recv(self, msg):
        """process further incoming messages"""
        stream = msg[0]&B_STREAM
        err = msg[0]&B_ERROR
        if stream and self.stream_in is not True and err:
            # This is a late-delivered incoming-stream-terminating error.
            return

        if self.msg is None or not stream:
            if self.msg is None:
                self._set_msg(msg)
            else:
                # this can happen when the stream ends
                # before the reader starts to retrieve data
                assert not stream
                self.msg2 = msg
        if stream:
            if self.stream_in is NotGiven:
                # reject: we don't accept incoming streams
                self.stream_in = False
                await self._send([E_NO_STREAM],{},err=True)
            elif self.stream_in is None:
                self.stream_in = True
            elif self.stream_in:
                if self.recv_q is None:
                    return  # closed on our side, ignore
                if err:
                    exc = StreamError(msg)
                    self.recv_q.put_nowait_error(exc)
                else:
                    self.recv_q.put_nowait(msg)
        else:
            if self.stream_in is not False:
                if self.recv_q is None:
                    raise EOFError  # drop
                self.recv_q.close_sender()
            self.stream_in = False
            if self.scope and err:
                self.scope.cancel()
                self.error = StreamError(msg)

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
        await self.parent._send(self._i|(B_STREAM if stream else 0)|(B_ERROR if err else 0), d,kw)

    def send(self, *a, **kw) -> Awaitable[None]:
        """
        Send a reply.
        Transmissions are auto-marked as belonging to the stream during streaming.
        """
        return self._send(a, kw if kw else None, stream=None)

    def send_error(self, *a, **kw) -> Awaitable[None]:
        return self._send(d, kw if kw else None, stream=None, err=True)

    async def stop(self, *err, **kw):
        """stops an incoming stream"""
        if not self.stream_in:
            return  # already closed
        i = self._i|B_ERROR
        if self.stream_out is False:
            i|= B_STREAM
        if not err:
            err = [E_UNSPEC]
        await self.parent._send(i, err, kw if kw else None)

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
        self.msg = self.cmd = self.data = None
        self.cmd_in = Event()
        if self.msg2 is not None:
            # This happens when an incoming stream is already finished
            self._set_msg(self.msg2)
            self.msg2 = None

        await self._send(d,kw, stream=sout)
        yield self
        pass # an end message must be sent, but ours is not the place


    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._recv_q is None:
            raise StopAsyncIteration
        return await self._recv_q.get()


