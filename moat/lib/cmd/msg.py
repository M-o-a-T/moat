"""
Basic message block
"""

from __future__ import annotations
from contextlib import asynccontextmanager
import outcome

from moat.util.compat import log, Event, Queue
from moat.util import Path, P
from .base import MsgLink
from .const import SD_IN, SD_OUT, SD_BOTH, SD_NONE
from .const import S_NEW, S_END, S_ON, S_OFF
from .const import E_NO_STREAM
from .const import B_STREAM, B_ERROR
from .errors import StreamError, Flow, NoStream, WantsStream

from typing import TYPE_CHECKING, overload

if TYPE_CHECKING:
    from typing import Self, Iterator


try:
    import logging
except ImportError:
    def log_exc(e,s,*a):
        log(s+": %r", *a, e)
else:
    logger = logging.getLogger(__name__)
    def log_exc(e,s,*a):
        logger.error(s, *a, exc_info=e)

class MsgResult:
    """
    This class encapsulates the result of a message, which is
    simultaneously a list and a dict. Both are read-only.

    You can access mutable versions with `args` and `kw`.
    """

    _a: list | None = None
    _kw: dict | None = None

    def __init__(self, a: list, kw: dict):
        self._a = a
        self._kw = kw

    @property
    def args(self) -> list:
        "Retrieve the argument list."
        return self._a

    @property
    def kw(self) -> dict:
        "Retrieve the keywords."
        return self._kw

    def __len__(self) -> int:
        return len(self._a)

    def __bool__(self) -> bool:
        return True

    def __getitem__(self, k: int | str) -> Any:
        """
        Get an item. If the key is numeric, retrieve from the argument
        list, else from the keywords.
        """
        if isinstance(k, int):
            return self._a[k]
        return self._kw[k]

    def get(self, k: int | str, default=None) -> Any:
        """
        Get an item. Like `__getitem__` but returns a default (None) instead of
        raising `KeyError` / `IndexError`.
        """
        if isinstance(k, int):
            try:
                return self._a[k]
            except IndexError:
                return default
        try:
            return self._kw[k]
        except KeyError:
            return default

    def __contains__(self, k) -> bool:
        if isinstance(k, int):
            return 0 <= k < len(self._a)
        return k in self._kw

    def __iter__(self) -> Self:
        "Returns an iterator over the list."
        if self._kw:
            raise ValueError("This message contains keywords.")
        return iter(self._a)

    def keys(self) -> Iterator[str]:
        "Returns an iterator over the dict's keys."
        return self._kw.keys()

    def values(self):
        "Returns an iterator over the dict's values."
        return self._kw.values()

    def items(self):
        "Returns an iterator over the dict's keys/value tuples."
        return self._kw.items()


class Msg(MsgLink, MsgResult):
    """
    Message encapsulation and data streaming.
    """

    # The multiple inheritance problem WRT µPy is resolved below.

    _cmd: Path | None = None
    _a: list | None = None
    _kw: dict | None = None

    _stream_in: int = S_NEW
    _stream_out: int = S_NEW

    _dir: int = SD_NONE

    _msg: outcome.Outcome | None = None
    _msg2: outcome.Outcome | None = None
    _msg_in: Event
    _recv_q: Queue | None = None
    _recv_qlen: int = 5
    _recv_skip: bool = False

    _flo_evt: Event | None = None
    warnings:list

    def __init__(self):
        """
        Set up the message.
        """
        super().__init__()
        self._msg_in = Event()
        self.warnings = []  # TODO

    @property
    def cmd(self) -> Path:
        "Retrieve the command."
        return self._cmd

    @property
    def rcmd(self) -> list[str]:
        """
        Retrieve a reversed command
        """
        res = list(self.cmd)
        res.reverse()
        return res

    @classmethod
    def Call(cls, cmd: Path, a: list, kw: dict, flags: int = 0) -> Self:
        """Constructor for a possibly-remote function call."""
        if isinstance(cmd, str):
            # XXX we might want to warn and/or error out here
            cmd = P(cmd)
        s = cls()
        s._cmd = cmd
        s._a = a
        s._kw = kw
        if flags & B_STREAM:
            s._stream_in = S_ON
        return s

    @property
    def remote(self) -> MsgLink:
        return self._remote

    def replace_with(self, link: MsgLink) -> None:
        """
        Tell my own remote to point to @link instead.
        """
        if (rem := self._remote) is None:
            # we are a straight command handler and don't yet have a remote.
            link.set_remote(self)
            self._remote = link
            return

        rem.set_remote(link)  # this kills self
        link.set_remote(rem)

    def kill(self, new: bool = False) -> None:
        """No further communication may happen on this message.

        If @new is set, this not being a "new" stream will raise a runtime
        exception.
        """
        try:
            if new:
                if rrem._stream_in != S_NEW:
                    raise RuntimeError("incoming already started")
                if rrem._stream_out != S_NEW:
                    raise RuntimeError("outgoing already started")
        finally:
            self._stream_in = S_END
            self._stream_out = S_END
            if self._msg_in is not None:
                self._msg_in.set()
            super().kill()


    async def ml_send(self, a: list, kw: dict, flags: int) -> None:
        """
        Sender of data to the other side.
        """
        if self._stream_out == S_END:
            return
        if not flags & B_STREAM:
            self._stream_out = S_END
        elif self._stream_out == S_NEW and not flags & B_ERROR:
            self._stream_out = S_ON
        await super().ml_send(a, kw, flags)

    async def ml_recv(self, a: list, kw: dict, flags: int) -> None:
        """
        Receiver for data from the other side.
        """
        # if S_END, no message may be exchanged
        # else if Stream bit is False, stop streaming if it is on, go to S_END: out of band
        # else if Error bit is True: flow / warning
        # else if S_NEW: go to S_ON: out-of-band
        # else: streamed data

        if self._stream_in == S_END:
            # This is a late-delivered incoming-stream-terminating error.
            log("LATE? L%d %r %r %d", self.link_id, a, kw, flags)

        elif not flags & B_STREAM:
            self._set_msg(a, kw, flags)
            self._stream_in = S_END
            if self._recv_q is not None:
                self._recv_q.close_sender()

        elif flags & B_ERROR:
            if kw:
                a.append(kw)
            exc = StreamError(a)
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
            elif self._stream_in == S_ON and self._recv_q is not None:
                await self._recv_q.put_error(exc)
            else:
                self.warnings.append(exc)

        elif self._stream_in == S_NEW:
            self._set_msg(a, kw, flags)
            self._stream_in = S_ON

        elif self._recv_q is not None:
            await self._recv_q.put((a, kw))

        else:
            log("Unwanted stream: %r/%r/%d", a, kw, flags)
            if self._stream_in == S_ON:
                self._stream_in = S_OFF
                if self._stream_out != S_END:
                    await self.ml_send([E_NO_STREAM], None, B_ERROR)
                    self._stream_out = S_END

        self._ended()

    async def send(self, *a, **kw) -> None:
        if self._stream_out != S_ON:
            raise NoStream
        await self._skipped()
        await self.ml_send(a, kw, B_STREAM)

    async def warn(self, *a, **kw) -> None:
        await self.ml_send(a, kw, B_STREAM | B_ERROR)

    async def error(self, *a, **kw) -> None:
        await self.ml_send(a, kw, B_ERROR)

    def _set_msg(self, a: list, kw: dict, flags: int) -> None:
        """
        A message has arrived on this stream. Store and set an event.
        """
        if flags & B_ERROR:
            msg = outcome.Error(StreamError(a))
        else:
            msg = outcome.Value((a, kw))

        if self._msg is None:
            self._msg = msg
            self._msg_in.set()
        elif self._msg2 is None:
            self._msg2 = msg
        else:
            raise RuntimeError("Msg Collision?")

    def _ended(self) -> None:
        """
        If message processing is finished, finalize processing this
        message. Otherwise do nothing.
        """
        if self._stream_in != S_END:
            return
        if self._stream_out != S_END:
            return
        self.kill()

    # Stream starters

    async def prep_stream(self, flag: int) -> None:
        """Sets up streaming as per SD_* flags.

        Sends an E_NO_STREAM warning if there's no streaming but queued data.
        """
        self._dir = flag

        if flag & SD_IN:
            if self._recv_q is None:
                self._recv_q = Queue(self._recv_qlen)
        else:
            q, self._recv_q = self._recv_q, None
            if q is not None and q.qsize() and self._stream_in == S_ON:
                self._stream_in = S_OFF
                await self.warn(E_NO_STREAM)
            # whatever has been received will be discarded

        self._stream_out = S_ON if flag & SD_OUT else S_OFF

    async def no_stream(self) -> None:
        """Mark as neither send or receive streaming."""
        if self._stream_in == S_ON:
            if self._stream_out != S_END:
                await self.error(E_NO_STREAM)
            raise WantsStream
        self._recv_q = None
        self._dir = 0
        # TODO

    # Stream reply helpers

    def stream_in(self, *data, **kw) -> AsyncContextManager[Msg]:
        return self._stream(data, kw, SD_IN)

    def stream_out(self, *data, **kw) -> AsyncContextManager[Msg]:
        return self._stream(data, kw, SD_OUT)

    def stream(self, *data, **kw) -> AsyncContextManager[Msg]:
        return self._stream(data, kw, SD_BOTH)

    def stream_call(self, flag: int) -> AsyncContextManager[Msg]:
        return self._stream(None, None, flag, initial=True)

    @property
    def can_stream(self) -> bool:
        """check whether this is a streaming command"""
        if self._stream_in != S_NEW or self._stream_out != S_NEW:
            return True
        if (rem := self.remote) is None:
            return False
        try:
            if rem._stream_in != S_NEW or rem._stream_out != S_NEW:
                return True
        except AttributeError:
            pass
        return False

    async def call_simple(self, cmd: Callable) -> None:
        """Handle a non-streamed call endpoint.

        @cmd is a callable that takes whichever arguments the message
        contains (hopefully).
        """
        try:
            res = cmd(*self._a, **self._kw)
            if hasattr(res, "__await__"):
                res = await res
        except Exception as exc:
            log_exc(exc,"Command Error %r", self)
            if self._remote is None:
                raise
            await self.ml_send((exc.__class__.__name__,) + exc.args, None, B_ERROR)
        except BaseException as exc:
            if self._remote is None:
                raise
            log_exc(exc, "Command Error %r", self)
            await self.ml_send((exc.__class__.__name__,) + exc.args, None, B_ERROR)
            raise
        else:
            await self.result(res)

    @asynccontextmanager
    async def ensure_remote(self):
        """
        A context mamager that adds a remote side to an existing message.
        """
        if (m := self._remote) is None:
            m = Msg.Call(self._cmd, self._a, self._kw)
            self._cmd, self._a, self._kw = None, (), {}
            m.set_remote(self)
            self.set_remote(m)
        try:
            yield m
        finally:
            m.kill()
            self.kill()

    async def call_stream(self, cmd: Callable) -> None:
        """Handle a streamed call endpoint.

        @cmd is an async callable that processes the message object.
        """
        # If this message is direct and doesn't yet have a counterpart,
        # create one and re-do the call on that.

        if self._remote is None:
            async with self.ensure_remote() as m:
                return await m.call_stream(cmd)
        try:
            await cmd(self)
        except Exception as exc:
            log_exc(exc,"Stream Error %r", self)
            await self.ml_send((exc.__class__.__name__,) + exc.args, None, B_ERROR)
        except BaseException as exc:
            log_exc(exc,"Stream Error %r", self)
            await self.ml_send((exc.__class__.__name__,) + exc.args, None, B_ERROR)
            raise

    @asynccontextmanager
    async def _stream(self, a: list, kw: dict, flag: int, initial: bool = False):
        if self._stream_out != S_NEW:
            raise RuntimeError(
                "Simple command" if self._stream_out == S_END else "Stream-out already set",
            )

        # stream-in depends on what the remote side sent
        await self.prep_stream(flag)

        if self._recv_qlen < 10:
            self._fli = 0
            await self.warn(self._recv_qlen)

        if initial:
            await self.wait_replied()
        else:
            await self.ml_send(a, kw, B_STREAM)
            # intentionally not async

        try:
            yield self
        finally:
            # This code is running inside the handler, which will process the error
            # case. Thus we don't need error handling here.

            if self._stream_out != S_END:
                await self.ml_send([None], {}, 0)

            await self.wait_replied()
            if self._stream_in != S_END:
                raise RuntimeError("Stream not ended")

    async def result(self, *a, **kw) -> None:
        """
        Send (or set) the result.
        """
        if self._remote is None:
            if self._msg is not None:
                if kw:
                    raise RuntimeError("Dup call", kw)
                if a and (len(a) > 1 or a[0] is not None):
                    raise RuntimeError("Dup call", a)

            self._msg = outcome.Value((a, kw))
            self._msg_in.set()
            return

        await self.ml_send(a, kw, 0)

    async def wait_replied(self) -> None:
        """
        Wait for a (non-streamed) reply.
        """
        if self._msg is None:
            if self._stream_in == S_END:
                raise NoStream()
            await self._msg_in.wait()
            self._msg_in = Event()
        msg = self._msg
        self._msg = self._msg2
        self._msg2 = None
        if msg is None:
            raise EOFError
        self._a, self._kw = msg.unwrap()

    def __aiter__(self) -> Self:
        return self

    async def _skipped(self):
        """
        Test whether incoming data could not be delivered due to the
        receive queue getting full.
        """
        if self._recv_q is not None and self._recv_skip and self.stream_out != S_END:
            await self.warn(E_SKIP)
            self._recv_skip = False

    async def _qsize(self) -> None:
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
            m = self._recv_qlen // 2 + 1
            self._fli -= m
            await self.warn(m)

        # - additionally, if the max queue is < 10
        #   we send a bit more aggressively, to reduce lag
        else:
            self._fli += 1
            if self._recv_qlen < 10 and self._fli >= self._recv_qlen // 4:
                m, self._fli = self._fli, 0
                await self.warn(m)

    async def __anext__(self) -> MsgResult:
        if self._recv_q is None:
            raise StopAsyncIteration
        elif isinstance(self._recv_q, Exception):
            exc, self._recv_q = self._recv_q, None
            raise exc
        await self._skipped()

        try:
            res = await self._recv_q.get()
        except EOFError:
            raise StopAsyncIteration

        await self._qsize()
        return MsgResult(*res)

    def __repr__(self):
        return f"<{self.__class__.__name__}:L{self.link_id} r{'=L' + str(self._remote.link_id) if self._remote else '-'}: {' ' + str(self._cmd) if self._cmd else ''} {self._a} {self._kw}>"


# no multiple inheritance for µPy

for k in dir(MsgResult):
    if not hasattr(Msg, k):
        setattr(Msg, k, getattr(MsgResult, k))
