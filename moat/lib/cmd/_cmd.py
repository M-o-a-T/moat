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
    from typing import Any, Protocol, AsyncContextManager
    from collections.abc import Callable, Awaitable

    class MsgIn(Protocol):
        def __call__(self, msg):
            pass


L = True

__all__ = [
    "Stream",
    "CmdHandler",
    "StreamError",
    "StopMe",
    "NoStream",
    "NoCmd",
    "NoCmds",
    "WantsStream",
    "MustStream",
]

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


def _exp(fn):  # [F: Callable[..., Any]](fn: F) -> F:
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
class StreamError(RuntimeError):
    def __new__(cls, msg=()):
        if len(msg) == 1 and isinstance((m := msg[0]), int):
            if m >= 0:
                return Flow(m)
            elif m == E_UNSPEC:
                return super().__new__(StopMe)
            elif m == E_NO_STREAM:
                return super().__new__(NoStream)
            elif m == E_MUST_STREAM:
                return super().__new__(MustStream)
            elif m == E_SKIP:
                return super().__new__(SkippedData)
            elif m == E_NO_CMDS:
                return super().__new__(NoCmds)
            elif m <= E_NO_CMD:
                return super().__new__(NoCmd, E_NO_CMD - m)
        return super().__new__(cls)

    pass


@_exp
class StopMe(StreamError):
    pass


@_exp
class SkippedData(StreamError):
    pass


@_exp
class NoStream(StreamError):
    pass


@_exp
class NoCmds(StreamError):
    pass


@_exp
class NoCmd(StreamError):
    pass


@_exp
class WantsStream(StreamError):
    pass


@_exp
class MustStream(StreamError):
    pass


@_exp
class CmdHandler(CtxObj):
    """
    This is a manager for multiplexed command/response interactions between
    two peers.

    All such interactions are independent of each other and may contain
    data streams.
    """

    def __init__(self, handler: MsgIn):
        self._msgs: dict[int, Stream] = {}
        self._id = 1
        self._send_q = Queue(9)
        self._recv_q = Queue(99)
        self._debug = logger.warning
        self._in_cb = handler

        self._id1 = set()
        if L:
            self._id2 = set()
        self._id3 = set()
        self._id = 0

    def _gen_id(self):
        # Generate the next free ID.
        # TODO
        if self._id1:
            return self._id1.pop()
        if L and self._id2:
            return self._id2.pop()
        if self._id3:
            return self._id3.pop()
        self._id += 1
        return self._id

    def attach(self, mid, proc, force: bool = False):
        """
        Attach a handler for raw incoming messages.
        """
        if not force and mid in self._msgs:
            raise ValueError(f"MID {mid} already known")
        self._msgs[mid] = proc

    def detach(self, mid, proc=None):
        """
        Remove a handler for raw incoming messages.
        """
        if proc is None or self._msgs[mid] == proc:
            try:
                del self._msgs[mid]
            except KeyError:
                if mid > 0:
                    raise
            if mid <= 0:
                return

            if mid < 6:
                self._id1.add(mid)
            elif L and mid < 64:
                self._id2.add(mid)
            else:
                self._id3.add(mid)

    def forward(self, msg, cmd):
        """
        Forward an otherwise-unhandled(!!) message to this stream, using
        this command vector. (Arguments and keywords are copied from the message.)

        This is not a coroutine by design.
        """
        return Forward(self, msg, cmd)

    def cmd_in(self) -> Awaitable[Stream]:
        """Retrieve new incoming commands"""
        return self._recv_q.get()

    async def cmd(self, *a, **kw):
        """Send a simple command, receive a simple reply."""
        i = self._gen_id()
        msg = Stream(self, i, s_in=False, s_out=False)
        self.attach(i, msg._recv)
        await msg._send(a, kw if kw else None)
        try:
            await msg.replied()
        except BaseException as exc:
            await msg.kill(exc)
            raise
        try:
            msg._unwrap()
            return msg
        except NoCmd as e:
            i = e.args[0]
            raise NoCmd(i, a[0][i], a, kw) from None
        finally:
            await msg.kill()

    def _drop(self, msg):
        if msg.stream_in != S_END or msg.stream_out != S_END:
            raise RuntimeError(f"Drop while in progress {msg}")
        self.detach(msg.id)

    async def _handle(self, msg):
        assert msg.id < 0, msg

        async def _final(msg, res, err):
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
                msg._ended()

        async def _wrap(msg, res, *, task_status):
            async with CancelScope() as cs:
                msg.scope = cs
                task_status.started()
                err = ()
                try:
                    if callable(res):
                        res = res(msg)
                    if hasattr(res, "__await__"):
                        res = await res
                except AssertionError:
                    raise
                except Exception as exc:
                    res = None
                    if msg.stream_out == S_END:
                        logger.error("Error not sent (msg=%r)", msg, exc_info=exc)
                    else:
                        err = (exc.__class__.__name__,) + tuple(exc.args)
                        logger.debug("Error (msg=%r)", msg, exc_info=exc)
                except BaseException:
                    res = None
                    err = (E_CANCEL,)
                    raise
                finally:
                    # terminate outgoing stream, if any
                    await _final(msg, res, err)

        try:
            res = self._in_cb(msg)
        except Exception as exc:
            self._debug("Error for %r suppressed: %r", msg, exc)
            await _final(msg, None, (exc.__class__.__name__,) + tuple(exc.args))
        else:
            if isinstance(res, Forward):
                res.start(self)
            elif callable(res) or hasattr(res, "__await__"):
                await self._tg.start(_wrap, msg, res)
            else:
                await _final(msg, res, ())

    def stream_r(self, *data, **kw) -> AsyncContextManager[Stream]:
        """Start an incoming stream"""
        return self._stream(data, kw, True, False)

    def stream_w(self, *data, **kw) -> AsyncContextManager[Stream]:
        """Start an outgoing stream"""
        return self._stream(data, kw, False, True)

    def stream_rw(self, *data, **kw) -> AsyncContextManager[Stream]:
        """Start a bidirectional stream"""
        return self._stream(data, kw, True, True)

    @asynccontextmanager
    async def _stream(self, d, kw, sin, sout):
        "Generic stream handler"
        i = self._gen_id()
        msg = Stream(self, i)
        self.attach(i, msg._recv)

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

    def _send(self, i, data, kw=None) -> Awaitable[None]:
        assert isinstance(data, (list, tuple)), data
        assert isinstance(i, int), i
        return self._send_q.put((i, data, kw))

    def _send_nowait(self, i, data, kw=None) -> None:
        assert isinstance(data, (list, tuple)), data
        assert isinstance(i, int), i
        self._send_q.put_nowait((i, data, kw))

    async def msg_out(self) -> None:
        i, d, kw = await self._send_q.get()

        # Handle last-arg-is-dict ambiguity
        if kw is None and d and isinstance(d[-1], dict):
            kw = {}
        return (i,) + tuple(d) + ((kw,) if kw is not None else ())

    async def msg_in(self, msg) -> None:
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
                if i > 0:
                    i -= 1
                self._send_nowait((i << 2) | B_ERROR, [E_NO_CMD])
            else:
                conv = Stream(self, i)
                self.attach(i, conv._recv)
                conv._recv(msg)
                await self._handle(conv)
        else:
            try:
                conv(msg)
            except EOFError:
                self.detach(i)

    @asynccontextmanager
    async def _ctx(self) -> Self:
        async with TaskGroup() as tg:
            self._tg = tg
            try:
                yield self
            finally:
                for conv in list(self._msgs.values()):
                    conv(None)
                tg.cancel()

        for k in list(self._msgs.keys()):
            self.detach(k)


@_exp
class Stream:
    """
    This object handles one conversation.
    It's also used as a message container.

    The last non-streamed incoming message's data are available in @msg.
    The first item of an initial message is stored in @cmd, if the last
    item is a mapping it's in @kw; the individual items can be accessed
    directly by indexing the message.
    """

    _cmd: Any  # first element of the message
    _args: list[Any]
    _kw: dict[str, Any]

    _fli = None  # flow control for incoming messages
    _flo = None  # flow control for outgoing messages
    _flo_evt = None
    _recv_skip = False
    _recv_q = None
    _recv_qlen = 0
    scope = None
    _msg: outcome.Outcome = None
    msg2 = None
    _initial = False
    s_out = False

    stream_out = S_NEW
    stream_in = S_NEW

    def __init__(self, parent: CmdHandler, mid: int, qlen=42, s_in=True, s_out=True):
        self.parent = parent
        self.id = mid
        if mid > 0:
            mid -= 1
        self._i = mid << 2  # ready for sending
        self.cmd_in: Event = Event()

        if s_in:
            self._recv_q = Queue(qlen)
            self._recv_qlen = qlen
        if s_out:
            self.s_out = s_out

    def __getitem__(self, k:int|str) -> Any:
        """
        Get an item. If the key is numeric, retrieve from the argument
        list, else from the keywords.
        """
        if isinstance(k, int):
            return self._args[k]
        return self._kw[k]

    def get(self, k:int|str, default=None) -> Any:
        """
        Get an item. Like `__getitem__` but returns a default (None) instead of
        raising `KeyError` / `IndexError`.
        """
        if isinstance(k, int):
            try:
                return self._args[k]
            except IndexError:
                return default
        try:
            return self._kw[k]
        except KeyError:
            return default

    def __contains__(self, k):
        if isinstance(k, int):
            return 0 <= k < len(self._args)
        return k in self._kw

    def __iter__(self):
        if self._kw:
            raise ValueError("This message contains keywords.")
        return iter(self._args)

    def __repr__(self):
        r = f"<Stream:{self.id}"
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
            r += " D:" + repr(msg)
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
                await self._send((exc.__class__.__name__,)+tuple(exc.args), err=True, _kill=True)
            else:  # BaseException
                await self._send([E_CANCEL], err=True, _kill=True)
                raise

        if self._recv_q is not None:
            try:
                self._recv_q.put_nowait_error(LinkDown())
            except EOFError:
                pass
            if self.stream_in == S_ON:
                self.stream_in = S_OFF

        self._ended()

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

    def __len__(self):
        self._unwrap()
        return len(self._args)

    def __bool__(self):
        return True

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
        self._kw = msg.pop() if msg and isinstance(msg[-1], dict) else {}
        self._cmd = msg.pop(0) if self._initial else None
        self._args = msg
        self._msg = None

    def _set_msg(self, msg):
        """
        A message has arrived on this stream. Store and set an event.
        """
        if self.stream_in == S_END:
            pass  # happens when msg2 is set
        else:
            self._initial = msg[0] >= 0 and self.stream_in == S_NEW
            if not (msg[0] & B_STREAM):
                self.stream_in = S_END
            elif self.stream_in == S_NEW and not (msg[0] & B_ERROR):
                self.stream_in = S_ON

        if msg[0] & B_ERROR:
            self._msg = outcome.Error(StreamError(msg[1:]))
        else:
            self._msg = outcome.Value(msg[1:])
        self.cmd_in.set()
        if self.stream_in != S_END:
            self.cmd_in = Event()
        else:
            self._ended()

    def _ended(self):
        """
        If message processing is finished, finalize processing this
        message. Otherwise do nothing.
        """
        if self.stream_in != S_END:
            return
        if self.stream_out != S_END:
            return
        if self.parent is None:
            return
        self.parent._drop(self)  # QA
        self.parent = None

    def _recv(self, msg: tuple[int, Any, ...]):
        """process an incoming messages on this stream"""
        if msg is None:
            self.kill_nc()
            return

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

        self._ended()

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
            self._i | (B_STREAM if stream else 0) | (B_ERROR if err else 0),
            d,
            kw,
        )
        self._ended()

    def _send_nowait(self, d, kw=None, stream=False, err=False, _kill=False) -> None:
        if self.parent is None:
            return
        self._sendfix(stream, err, _kill)
        self.parent._send_nowait(
            self._i | (B_STREAM if stream else 0) | (B_ERROR if err else 0),
            d,
            kw,
        )
        self._ended()

    async def _skipped(self):
        """
        Test whether incoming data could not be delivered due to the
        receive queue getting full.
        """
        if self._recv_q is not None and self._recv_skip and self.stream_out != S_END:
            await self.warn(E_SKIP)
            self._recv_skip = False

    async def _qsize(self, reading: bool = False):
        # Incoming message queue handling strategy:
        # - read without flow control until the queue is half full
        if self._fli is None:
            if self._recv_q.qsize() >= self._recv_qlen // 2:
                self._fli = 0
                # - send a message announcing 1/4 of the queue space
                await self.warn(self._recv_qlen // 4)

        # - then, whenever the queue is at most 1/4 full *and* qlen/2 messages
        #   have been processed (which will happen because the queue was
        #   half-full when we started), announce that space
        elif self._recv_q.qsize() <= self._recv_qlen // 4 and self._fli > self._recv_qlen // 2:
            m = self._recv_qlen // 2 + reading
            self._fli -= m
            await self.warn(m)

        # - additionally, if the max queue is < 10
        #   we send a bit more aggressively, to reduce lag
        elif reading:
            self._fli += 1
            if self._recv_qlen < 10 and self._fli >= self._recv_qlen // 4:
                m, self._fli = self._fli, 0
                await self.warn(self._fli)

    async def send(self, *a, **kw) -> None:
        """
        Send a (streamed) reply message.
        """
        await self._skipped()

        if self.stream_out != S_ON or not self.s_out:
            raise NoStream

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

    def error_nowait(self, *a, **kw) -> None:
        """
        Send an error.
        """
        return self._send_nowait(a, kw if kw else None, stream=False, err=True)

    def warn(self, *a, **kw) -> Awaitable[None]:
        """
        Send a warning.
        """
        return self._send(a, kw if kw else None, stream=True, err=True)

    def warn_nowait(self, *a, **kw) -> None:
        """
        Send a warning.
        """
        return self._send_nowait(a, kw if kw else None, stream=True, err=True)

    def result(self, *a, **kw) -> Awaitable[None]:
        """
        Send the result.
        """
        return self._send(a, kw if kw else None, stream=False, err=False)

    def result_nowait(self, *a, **kw) -> None:
        """
        Send the result.
        """
        return self._send_nowait(a, kw if kw else None, stream=False, err=False)

    # Stream starters

    async def no_stream(self):
        """Mark as neither send or receive streaming."""
        if self.stream_in == S_ON:
            if self.stream_out != S_END:
                await self.error(E_NO_STREAM)
            raise WantsStream
        self._recv_q = None
        self.s_out = False
        # TODO

    def stream_r(self, *data, **kw) -> AsyncContextManager[Stream]:
        return self._stream(data, kw, True, False)

    def stream_w(self, *data, **kw) -> AsyncContextManager[Stream]:
        return self._stream(data, kw, False, True)

    def stream_rw(self, *data, **kw) -> AsyncContextManager[Stream]:
        return self._stream(data, kw, True, True)

    @asynccontextmanager
    async def _stream(self, d, kw, sin, sout):
        if self.stream_out != S_NEW:
            raise RuntimeError(
                "Simple command" if self.stream_out == S_END else "Stream-out already set"
            )

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

    async def replied(self) -> None:
        if self._msg is None:
            await self.cmd_in.wait()

    def __aiter__(self):
        self._unwrap()
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


@_exp
class Forward:
    """
    Container for message forwarding
    """

    end_src = False
    end_dst = False
    src_id: int
    dst_id: int

    def __init__(self, hdl: CmdHandler, msg: Stream, cmd: tuple[Any, ...]):
        self.dst = hdl
        self.msg = msg
        self.cmd = cmd

    def start(self, hdl: CmdHandler):
        """
        Init and orchestrate the forwarding process.
        """
        self.src = hdl

        self.src_id = self.msg.id
        self.dst_id = self.dst._gen_id()
        self._src_id = self.src_id - (self.src_id > 0)
        self._dst_id = self.dst_id - (self.dst_id > 0)

        self.src.attach(self.src_id, self.recv_src, force=True)
        self.dst.attach(self.dst_id, self.recv_dst)

        self.dst._send_nowait(
            (self._dst_id << 2) | (B_STREAM if self.msg.stream_in != S_END else 0),
            (self.cmd,) + tuple(self.msg._args),
            self.msg._kw,
        )

        del self.msg

    def recv_src(self, msg):
        """forward an incoming messages on the source stream to the destination"""
        if msg is None:
            self._ended(True)
            return

        stream = msg[0] & B_STREAM
        err = msg[0] & B_ERROR

        if self.end_src:
            logger.warning("LATE? %d/%d, %r", self.src_id, self.dst_id, msg)
            return  # ignore followup
        elif not stream:
            self.end_src = True

        kw = msg[-1] if len(msg) > 1 and isinstance(msg[-1], dict) else None
        args = msg[1:-1] if kw is not None else msg[1:]
        self.dst._send_nowait(
            (self._dst_id << 2) | (B_STREAM if stream else 0) | (B_ERROR if err else 0), args, kw
        )

        self._ended()

    def recv_dst(self, msg):
        """forward an incoming messages on the destination stream to the source"""
        if msg is None:
            self._ended(True)
            return

        stream = msg[0] & B_STREAM
        err = msg[0] & B_ERROR

        if self.end_dst:
            logger.warning("LATE? %d/%d, %r", self.dst_id, self.src_id, msg)
            return  # ignore followup
        elif not stream:
            self.end_dst = True

        kw = msg[-1] if len(msg) > 1 and isinstance(msg[-1], dict) else None
        args = msg[1:-1] if kw is not None else msg[1:]
        self.src._send_nowait(
            (self._src_id << 2) | (B_STREAM if stream else 0) | (B_ERROR if err else 0), args, kw
        )

        self._ended()

    def _ended(self, force: bool = False):
        if force:
            self.end_src = self.end_dst = True
        elif not self.end_src or not self.end_dst:
            return

        self.src.detach(self.src_id)
        self.dst.detach(self.dst_id)
