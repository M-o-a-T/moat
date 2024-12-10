from __future__ import annotations

from moat.util import Queue, CtxObj, QueueFull
from moat.util.compat import TaskGroup, CancelScope, const, CancelledError
from contextlib import asynccontextmanager
import outcome

try:
    from anyio import Event
except ImportError:
    from asyncio import Event

import logging

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Callable, Any, Awaitable, Protocol, AsyncContextManager

    class MsgIn(Protocol):
        def __call__(self, msg: Msg, /) -> Any: ...


logger = logging.getLogger(__name__)

# Lib/enum.py is *large*.

# bitfields

B_STREAM = const(1)
B_ERROR = const(2)

# errors

E_UNSPEC = const(-1)
E_NO_STREAM = const(-2)
E_CANCEL = const(-3)
E_NO_CMDS = const(-4)
E_SKIP = const(-5)
E_MUST_STREAM = const(-6)
E_NO_CMD = const(-11)

# Stream states

S_END = const(3)  # terminal Stream=False message has been sent/received
S_NEW = const(4)  # No incoming message yet
S_ON = const(5)  # we're streaming (seen/sent first message)
S_OFF = const(6)  # in: we don't want streaming and signalled NO

# if S_END, no message may be exchanged
# else if Stream bit is False, stop streaming if it is on, go to S_END: out-of-band
# else if Error bit is True: warning / out-of-band
# else if S_NEW: go to S_ON: out-of-band
# else: streamed data

__all__ = []


def _exp[F: Callable[..., Any]](fn: F) -> F:
    "export this"
    __all__.append(fn.__name__)
    return fn


@_exp
class LinkDown(RuntimeError):
    pass


class Flow:
    def __init__(self, n):
        self.n = n


@_exp
class StopMe(RuntimeError):
    pass


@_exp
class NoStream(RuntimeError):
    pass


@_exp
class NoCmds(RuntimeError):
    pass


@_exp
class NoCmd(RuntimeError):
    pass


@_exp
class WantsStream(RuntimeError):
    pass


@_exp
class MustStream(RuntimeError):
    pass


@_exp
class StreamError(RuntimeError):
    def __new__(cls, msg):
        if len(msg) == 1 and isinstance((m := msg[0]), int):
            if m >= 0:
                return Flow(m)
            elif m == E_UNSPEC:
                return StopMe()
            elif m == E_NO_STREAM:
                return NoStream()
            elif m == E_MUST_STREAM:
                return MustStream()
            elif m == E_NO_CMDS:
                return NoCmds()
            elif m <= E_NO_CMD:
                return NoCmd(E_NO_CMD - m)
        return super().__new__(cls)

    pass


@_exp
class CmdHandler(CtxObj):
    """
    This is a manager for multiplexed command/response interactions between
    two peers.

    All such interactions are independent of each other and may contain
    data streams.
    """

    def __init__(self, callback: MsgIn):
        self._msgs: dict[int, Msg] = {}
        self._id = 1
        self._send_q = Queue(9)
        self._recv_q = Queue(99)
        self._debug = logger.warning
        self._in_cb = callback

    def _gen_id(self):
        # Generate the next free ID.
        # TODO
        i = self._id
        while i < 6:
            if i not in self._msgs:
                self._id = i
                return i
            i += 1
        i = 1
        while i in self._msgs:
            i += 1
        self._id = i
        return i

    def cmd_in(self) -> Awaitable[Msg]:
        """Retrieve new incoming commands"""
        return self._recv_q.get()

    async def cmd(self, *a, **kw):
        """Send a simple command, receive a simple reply."""
        i = self._gen_id()
        self._msgs[i] = msg = Msg(self, i, s_in=False, s_out=False)
        self.add(msg)
        await msg._send(a, kw if kw else None)
        try:
            await msg.replied()
        except BaseException as exc:
            await msg.kill(exc)
            raise
        try:
            res = msg._msg.unwrap()
            if len(res) > 1 and isinstance(res[-1],dict) and not res[-1] and isinstance(res[-2],dict):
                res = res[:-1]
            return res
        finally:
            await msg.kill()

    def add(self, msg):
        if msg.stream_in != S_NEW or msg.stream_out != S_NEW:
            raise RuntimeError(f"Add while not new {msg}")
        self._msgs[msg.id] = msg

    def drop(self, msg):
        if msg.stream_in != S_END or msg.stream_out != S_END:
            raise RuntimeError(f"Drop while in progress {msg}")
        del self._msgs[msg.id]

    async def _handle(self, msg):
        assert msg.id < 0, msg

        async def _wrap(msg, task_status):
            async with CancelScope() as cs:
                msg.scope = cs
                task_status.started()
                err = ()
                res = None
                try:
                    await msg.replied()
                    res = await self._in_cb(msg)
                except AssertionError:
                    raise
                except Exception as exc:
                    if msg.stream_out == S_END:
                        logger.error("Error not sent (msg=%r)", msg, exc_info=exc)
                    else:
                        err = (exc.__class__.__name__, *exc.args)
                        logger.debug("Error (msg=%r)", msg, exc_info=exc)
                except BaseException:
                    err = (E_CANCEL,)
                    raise
                finally:
                    # terminate outgoing stream, if any
                    if msg.stream_out == S_END:  # already sent last msg!
                        if res is not None:
                            self._debug("Result for %r suppressed: %r", msg, res)
                        if err:
                            self._debug("Error for %r suppressed: %r", msg, err)
                    elif err:
                        await msg.error(*err)
                    else:
                        await msg.result(res)

                    # Handle termination.
                    if msg.stream_in != S_END:
                        msg._recv_q = None
                    else:
                        assert msg.id < 0, msg
                        msg.ended()

        await self._tg.start(_wrap, msg)

    def stream_r(self, *data, **kw) -> AsyncContextManager[Msg]:
        """Start an incoming stream"""
        return self._stream(data, kw, True, False)

    def stream_w(self, *data, **kw) -> AsyncContextManager[Msg]:
        """Start an outgoing stream"""
        return self._stream(data, kw, False, True)

    def stream_rw(self, *data, **kw) -> AsyncContextManager[Msg]:
        """Start a bidirectional stream"""
        return self._stream(data, kw, True, True)

    @asynccontextmanager
    async def _stream(self, d, kw, sin, sout):
        "Generic stream handler"
        i = self._gen_id()
        self._msgs[i] = msg = Msg(self, i)

        # avoid creating an inner cancel scope
        async with CancelScope() as cs:
            msg.scope = cs
            async with msg._stream(d, kw, sin, sout):
                try:
                    yield msg
                except BaseException as exc:
                    await msg.kill(exc)
                    raise
                else:
                    await msg.kill()

    def _send(self, i, data, kw=None):
        assert isinstance(data, (list, tuple)), data
        assert isinstance(i, int), i
        return self._send_q.put((i, data, kw))

    def _send_nowait(self, i, data, kw=None):
        assert isinstance(data, (list, tuple)), data
        assert isinstance(i, int), i
        self._send_q.put_nowait((i, data, kw))

    async def msg_out(self):
        i, d, kw = await self._send_q.get()

        # this is somewhat inefficient but oh well
        if kw is None and isinstance(d[-1], dict):
            kw = {}
        if kw is None:
            return (i,) + tuple(d)
        else:
            return (i,) + tuple(d) + (kw,)

    async def msg_in(self, msg):
        i = msg[0]
        # stream = i & B_STREAM
        error = i & B_ERROR
        i = -1 - (i >> 2)
        if i >= 0:
            i += 1
        try:
            conv = self._msgs[i]
        except KeyError:
            if i > 0:
                self._debug("Spurious message %r", msg)
            elif error:
                self._debug("Spurious error %r", msg)
            elif self._in_cb is None:
                self._send_nowait((i << 2) | B_ERROR, [E_NO_CMD])
            else:
                self._msgs[i] = conv = Msg(self, i)
                await self._handle(conv)
                await conv._recv(msg)
        else:
            try:
                await conv._recv(msg)
            except EOFError:
                del self._msgs[i]

    @asynccontextmanager
    async def _ctx(self):
        async with TaskGroup() as tg:
            self._tg = tg
            try:
                yield self
            finally:
                for conv in self._msgs.values():
                    conv.kill_nc()
                tg.cancel()
        self._msgs = {}


@_exp
class Msg:
    """
    This object handles one conversation.
    It's also used as a message container.

    The last non-streamed incoming message is available in @msg.
    The first item in the message is stored in @cmd, if the last item is a
    mapping it's in @data and individual keys can be accessed by indexing
    the message.
    """

    def __init__(self, parent: CmdHandler, mid: int, qlen=42, s_in=True, s_out=True):
        self.parent = parent
        self.id = mid
        if mid > 0:
            mid -= 1
        self._i = mid << 2  # ready for sending
        self.stream_out = S_NEW
        self.stream_in = S_NEW
        self.cmd_in: Event = Event()
        self.msg2 = None

        self._msg: list = None
        self._cmd: Any = None  # first element of the message
        self._data: dict = {}  # last element, if dict

        self._recv_q = Queue(qlen) if s_in else None
        self._recv_qlen = qlen
        self._fli = None  # flow control for incoming messages
        self._flo = None  # flow control for outgoing messages
        self._flo_evt = None
        self._recv_skip = False
        self.scope = None
        self.s_out = s_out
        self._initial = False

    def __getitem__(self, k):
        return self.data[k]

    def __contains__(self, k):
        return k in self.data

    def __repr__(self):
        r = f"<Msg:{self.id}"
        if self.stream_out != S_END:
            r += " O"
            if self.stream_out == S_NEW:
                r += "?"
            elif self.stream_out == S_ON:
                r += "+"
            elif self.stream_out == S_OFF:
                r += "-"
            else:
                r += repr(self.stream_out)
            if self._flo is not None:
                r += repr(self._flo)
        if self.stream_in != S_END:
            r += " I"
            if self.stream_in == S_NEW:
                r += "?"
            elif self.stream_in == S_ON:
                r += "+"
            elif self.stream_in == S_OFF:
                r += "-"
            else:
                r += repr(self.stream_in)
            if self._fli is not None:
                r += repr(self._fli)
        msg = self._msg
        if msg is not None:
            r += " D:"+repr(msg)
        return r + ">"

    async def kill(self, exc=None):
        """
        Stop this stream.
        """
        if self.parent is None:
            return

        if self.stream_out != S_END:
            self.stream_out = S_END

            if exc is None:
                await self._send([None], _kill=True)
            elif exc is True:
                await self._send([E_UNSPEC], err=True, _kill=True)
            elif isinstance(exc, Exception):
                await self._send(
                    (exc.__class__.__name__, *exc.args), err=True, _kill=True
                )
            else:  # BaseException
                await self._send([E_CANCEL], err=True, _kill=True)

        if self._recv_q is not None:
            try:
                self._recv_q.put_nowait_error(LinkDown())
            except EOFError:
                pass
            if self.stream_in == S_ON:
                self.stream_in = S_OFF

        self.ended()

    def kill_nc(self, exc=None):
        """
        Stop this stream (backend died).
        """
        self.stream_out = S_END
        self.stream_in = S_OFF
        self.cmd_in.set()
        if self._recv_q is not None:
            try:
                self._recv_q.put_nowait_error(LinkDown())
            except EOFError:
                pass

    @property
    def cmd(self):
        "Retrieve the command."
        self._unwrap()
        return self._cmd

    @property
    def args(self):
        "Retrieve the argument list. NB the command is *not* removed."
        self._unwrap()
        return self._args

    @property
    def kw(self):
        "Retrieve the keywords."
        self._unwrap()
        return self._kw

    def _unwrap(self):
        # disassemble the message.
        if not isinstance(self._msg, outcome.Outcome):
            return
        msg = self._msg.unwrap()
        self._kw = msg.pop() if isinstance(msg[-1], dict) else None
        self._cmd = msg.pop(0) if self._initial else None
        self._args = msg
        self._msg = None

    def _set_msg(self, msg):
        if self.stream_in == S_END:
            pass  # happens when msg2 is set
        else:
            self._initial = msg[0] >= 0 and self.stream_in == S_NEW
            if not (msg[0] & B_STREAM):
                self.stream_in = S_END
            elif self.stream_in == S_NEW and not (msg[0] & B_ERROR):
                self.stream_in = S_ON

        if isinstance(msg,tuple):
            breakpoint()
        if msg[0] & B_ERROR:
            self._msg = outcome.Error(StreamError(msg[1:]))
        else:
            self._msg = outcome.Value(msg[1:])
        self.cmd_in.set()
        if self.stream_in != S_END:
            self.cmd_in = Event()
        else:
            self.ended()

    def ended(self):
        if self.stream_in != S_END:
            return
        if self.stream_out != S_END:
            return
        if self.parent is None:
            return
        self.parent.drop(self)
        self.parent = None

    async def _recv(self, msg):
        """process an incoming messages on this stream"""
        stream = msg[0] & B_STREAM
        err = msg[0] & B_ERROR

        # if S_END, no message may be exchanged
        # else if Stream bit is False, stop streaming if it is on, go to S_END: out of band
        # else if Error bit is True: flow / warning
        # else if S_NEW: go to S_ON: out-of-band
        # else: streamed data

        if self.stream_in == S_END:
            # This is a late-delivered incoming-stream-terminating error.
            logger.warning("LATE? %r", msg)

        elif not stream:
            self._set_msg(msg)
            self.stream_in = S_END
            if self._recv_q is not None:
                self._recv_q.close_sender()

        elif err:
            exc = StreamError(msg)
            if isinstance(exc, Flow):
                if self._flo_evt is None:
                    self._flo = exc.n
                    self._flo_evt = Event()
                else:
                    if self._flo == 0:
                        self._flo_evt.set()
                        self._flo_evt = Event()
                    self._flo += exc.n
                # otherwise ignore
            elif isinstance(exc, CancelledError) and self.scope is not None:
                self.scope.cancel()
            elif self.stream_in == S_ON and self._recv_q is not None:
                self._recv_q.put_nowait_error(exc)
            else:
                self.warn.append(exc)

        elif self.stream_in == S_NEW:
            self._set_msg(msg)

        elif self._recv_q is not None:
            try:
                self._recv_q.put_nowait(msg[1:])
            except QueueFull:
                self._recv_skip = True

        else:
            self.parent._debug("Unwanted stream: %r", msg)
            if self.stream_in == S_ON:
                self.stream_in = S_OFF
                if self.stream_out != S_END:
                    self._send_nowait([E_NO_STREAM], err=True)
                    self.stream_out = S_END

        self.ended()

    def _sendfix(self, stream: bool, err: bool, _kill: bool):
        if stream is None:
            stream = self.stream_out == S_ON
        if self.stream_out == S_END and not _kill:
            raise RuntimeError("already replied")
        if self.stream_out == S_NEW and stream and not err:
            self.stream_out = S_ON
        elif not stream:
            self.stream_out = S_END

    async def _send(self, d, kw=None, stream=False, err=False, _kill=False) -> None:
        if self.parent is None:
            return
        self._sendfix(stream, err, _kill)
        await self.parent._send(
            self._i | (B_STREAM if stream else 0) | (B_ERROR if err else 0), d, kw
        )
        self.ended()

    def _send_nowait(self, d, kw=None, stream=False, err=False, _kill=False) -> None:
        if self.parent is None:
            return
        self._sendfix(stream, err, _kill)
        self.parent._send_nowait(
            self._i | (B_STREAM if stream else 0) | (B_ERROR if err else 0), d, kw
        )
        self.ended()

    async def _skipped(self):
        """
        Test whether incoming data could not be delivered due to the
        receive queue getting full.
        """
        if self._recv_q is not None and self._recv_skip and self.stream_out != S_END:
            await self.warn(E_SKIP)
            self._recv_skip = False

    async def _qsize(self, reading: bool = False):
        # Queueing strategy:
        # - read without flow control until the queue is half full
        # - send a message announcing 1/4 of the queue space
        # - then, whenever the queue is at most 1/4 full *and* qlen/2 messages
        #   have been processed, announce that space
        if self._fli is None:
            if self._recv_q.qsize() >= self._recv_qlen // 2:
                self._fli = 0
                await self.warn(self._recv_qlen // 4)

        elif (
            self._recv_q.qsize() <= self._recv_qlen // 4
            and self._fli > self._recv_qlen // 2
        ):
            m = self._recv_qlen // 2 + reading
            self._fli -= m
            await self.warn(m)

        elif reading:
            self._fli += 1
            if self._recv_qlen < 10 and self._fli >= self._recv_qlen // 4:
                m, self._fli = self._fli, 0
                await self.warn(self._fli)

    async def send(self, *a, **kw) -> None:
        """
        Send a reply.
        """
        await self._skipped()

        if self.stream_out != S_ON or not self.s_out:
            raise NoStream()

        if self.stream_out == S_ON and self._flo_evt is not None:
            while self._flo <= 0:
                await self._flo_evt.wait()
            self._flo -= 1
        await self._send(a, kw if kw else None, stream=True)

    def error(self, *a, **kw) -> Awaitable[None]:
        """
        Send an error.
        """
        return self._send(a, kw if kw else None, stream=False, err=True)

    def warn(self, *a, **kw) -> Awaitable[None]:
        """
        Send a warning.
        """
        return self._send(a, kw if kw else None, stream=True, err=True)

    def result(self, *a, **kw) -> Awaitable[None]:
        """
        Send the result.
        """
        return self._send(a, kw if kw else None, stream=False, err=False)

    # Stream starters

    async def no_stream(self):
        """Mark as neither send or receive streaming."""
        if self.stream_in == S_ON:
            if self.stream_out != S_END:
                await self.error(E_NO_STREAM)
            raise WantsStream()
        self._recv_q = None
        self.s_out = False
        # TODO

    def stream_r(self, *data, **kw) -> AsyncContextManager[Msg]:
        return self._stream(data, kw, True, False)

    def stream_w(self, *data, **kw) -> AsyncContextManager[Msg]:
        return self._stream(data, kw, False, True)

    def stream_rw(self, *data, **kw) -> AsyncContextManager[Msg]:
        return self._stream(data, kw, True, True)

    @asynccontextmanager
    async def _stream(self, d, kw, sin, sout):
        if self.stream_out != S_NEW:
            raise RuntimeError("Stream-out already set")

        # stream-in depends on what the remote side sent
        if not sin:
            q, self._recv_q = self._recv_q, None
            if q is not None and q.qsize() and self.stream_in == S_ON:
                self.stream_in = S_OFF
                await self.warn(E_NO_STREAM)
            # At this point the msg should not have been iterated yet
            # thus whatever has been received is still in there

        self.s_out = sout

        if self._recv_qlen < 10:
            self._fli = 0
            await self.warn(self._recv_qlen)

        await self._send(d, kw, stream=True)
        if self._i >= 0:
            # Wait for the initial reply if we're the sender.
            await self.replied()

        yield self

        # This code is running inside the handler, which will process the error
        # case. Thus we don't need error handling here.

        if self.stream_out != S_END:
            await self._send([None])

        if self.stream_in == S_END:
            pass
        elif self.msg2 is None:
            self._msg = None
            await self.replied()
        else:
            self._set_msg(self.msg2)
            self.msg2 = None

    async def replied(self) -> Awaitable[None]:
        if self._msg is None:
            await self.cmd_in.wait()

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._recv_q is None:
            raise StopAsyncIteration
        elif isinstance(self._recv_q, Exception):
            exc, self._recv_q = self._recv_q, None
            raise exc
        await self._skipped()
        await self._qsize(True)

        try:
            return await self._recv_q.get()
        except EOFError:
            raise StopAsyncIteration
