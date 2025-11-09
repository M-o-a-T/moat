"""
Basic message block
"""

from __future__ import annotations

from moat.util import ExpectedError, Path, outcome
from moat.lib.codec.errors import SilentRemoteError
from moat.util.compat import Event, Queue, is_async, log, shield

from .base import MsgLink
from .const import (
    B_ERROR,
    B_STREAM,
    E_CANCEL,
    E_NO_STREAM,
    E_SKIP,
    S_END,
    S_NEW,
    S_OFF,
    S_ON,
    SD_BOTH,
    SD_IN,
    SD_NONE,
    SD_OUT,
)
from .errors import Flow, NoStream, StreamError, WantsStream

from typing import TYPE_CHECKING, cast

try:
    from collections.abc import Iterable
except ImportError:
    Iterable = object

try:
    from collections.abc import MutableMapping, MutableSequence
except ImportError:
    MutableSequence = list  # pyright:ignore
    MutableMapping = dict  # pyright:ignore

if TYPE_CHECKING:
    from contextlib import AbstractAsyncContextManager

    from .base import OptDict

    from collections.abc import Callable, ItemsView, Iterator, KeysView, Sequence, ValuesView
    from typing import Any, Self


try:
    import logging
except ImportError:
    from moat.util.compat import print_exc

    def log_exc(e, s, *a):  # noqa: D103
        log(s + ": %r", *a, e)
        print_exc(e)

else:
    logger = logging.getLogger(__name__)

    def log_exc(e, s, *a):  # noqa: D103
        logger.error(s, *a, exc_info=e)


class MsgResult(Iterable):
    """
    This class encapsulates the result of a message, which is
    simultaneously a list and a dict. Both are read-only.

    You can access mutable versions with `args` and `kw`.
    """

    _a: Sequence
    _kw: OptDict

    def __init__(self, a: list, kw: dict):
        self._a = a
        self._kw = kw

    def __repr__(self):
        return f"<{self.__class__.__name__}: {self._a} {self._kw}>"

    @property
    def args(self) -> Sequence:
        "Retrieve the argument list."
        return self._a

    @property
    def args_l(self) -> MutableSequence:  # pyright:ignore
        "Retrieve the argument list as a list."
        if not isinstance(self._a, MutableSequence):
            self._a = list(self._a)
        return self._a

    @property
    def kw(self) -> dict[str, Any]:
        "Retrieve the keywords."
        if self._kw is None:
            return {}
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
        if isinstance(k, (int, slice)):
            return self._a[k]
        return self._kw[k]  # pyright:ignore

    def get(self, k: int | str, default=None, nulled=False) -> Any:
        """
        Get an item. Like `__getitem__` but returns a default (None) instead of
        raising `KeyError` / `IndexError`.
        """
        if isinstance(k, int):
            try:
                res = self._a[k]
            except IndexError:
                return default
        else:
            try:
                res = self._kw[k]  # pyright:ignore
            except KeyError:
                return default

        if nulled and res is None:
            return default
        return res

    def __contains__(self, k) -> bool:
        if isinstance(k, int):
            return 0 <= k < len(self._a)
        return k in self._kw

    def __iter__(self) -> Iterator:
        "Returns an iterator over the list."
        return iter(self._a)

    def keys(self) -> KeysView:
        "Returns an iterator over the dict's keys."
        return self._kw.keys()  # pyright:ignore

    def values(self) -> ValuesView:
        "Returns an iterator over the dict's values."
        return self._kw.values()  # pyright:ignore

    def items(self) -> ItemsView:
        "Returns an iterator over the dict's keys/value tuples."
        return self._kw.items()  # pyright:ignore


class Msg(MsgLink, MsgResult):
    """
    Message encapsulation and data streaming.
    """

    # The multiple inheritance problem WRT µPy is resolved below.

    _cmd: Path | None = None
    _a: Sequence  # pyright:ignore
    _kw: OptDict  # pyright:ignore
    # also in MsgResult

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
    warnings: list

    _loaded: bool = False

    def __init__(self):
        """
        Set up the message.
        """
        super().__init__()
        self._msg_in = Event()
        self.warnings = []  # TODO

    @property
    def cmd(self) -> Path | None:
        "Retrieve the command."
        return self._cmd

    @property
    def rcmd(self) -> list[str]:
        """
        Retrieve a reversed command
        """
        assert self.cmd is not None
        res = list(self.cmd)
        res.reverse()
        return res

    @classmethod
    def Call(cls, cmd: Path, a: list, kw: dict, flags: int = 0) -> Self:
        """Constructor for a possibly-remote function call."""
        if isinstance(cmd, str):
            if ":" in cmd or "." in cmd:
                raise ValueError("Wrap command paths in a `P()` call")
            cmd = Path.build((cmd,))
        s = cls()
        s._cmd = cmd
        s._a = a
        s._kw = kw
        if flags & B_STREAM:
            s._stream_in = S_ON
        return s

    @property
    def remote(self) -> MsgLink:  # noqa: D102
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

    async def kill(self, new: bool = False) -> None:
        """No further communication may happen on this message.

        If @new is set, this not being a "new" stream will raise a runtime
        exception.
        """
        try:
            if new:
                if self._stream_in != S_NEW:
                    raise RuntimeError("incoming already started")
                if self._stream_out != S_NEW:
                    raise RuntimeError("outgoing already started")
        finally:
            self._stream_in = S_END
            self._stream_out = S_END
            if self._msg_in is not None:
                self._msg_in.set()
            await super().kill()

    async def ml_send(
        self, a: Sequence, kw: OptDict | None, flags: int, initial: bool | None = None
    ) -> None:
        """
        Sender of data to the other side.
        """
        if self._stream_out == S_END:
            return
        if not flags & B_STREAM:
            self._stream_out = S_END
        else:
            if self._stream_out == S_NEW and not flags & B_ERROR:
                self._stream_out = S_ON
            if initial is False and self._stream_in == S_NEW:
                self._stream_in = S_ON
        await super().ml_send(a, kw, flags)

    async def ml_recv(self, a: Sequence, kw: OptDict | None, flags: int) -> None:
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
            if not flags & B_ERROR or len(a) != 1 or a[0] != E_CANCEL:
                # Don't log if cancelled
                log("LATE? L%d %r %r %d", self.link_id, a, kw, flags)

        elif not flags & B_STREAM:
            self._set_msg(a, kw, flags)
            self._stream_in = S_END
            if self._stream_out == S_ON:
                self._stream_out = S_OFF
            if self._recv_q is not None:
                self._recv_q.close_sender()

        elif flags & B_ERROR:
            if kw:
                if not hasattr(a, "append"):
                    a = list(a)
                a = cast(list, a)
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

        await self._ended()

    async def send(self, *a, **kw) -> None:  # noqa: D102
        if not self._dir & SD_OUT:
            raise RuntimeError("This stream is read only")
        if self._stream_out != S_ON:
            raise NoStream
        await self._skipped()
        await self.ml_send(a, kw, B_STREAM)

    async def warn(self, *a, **kw) -> None:  # noqa: D102
        await self.ml_send(a, kw, B_STREAM | B_ERROR)

    async def error(self, *a, **kw) -> None:  # noqa: D102
        await self.ml_send(a, kw, B_ERROR)

    def _set_msg(self, a: Sequence, kw: OptDict | None, flags: int) -> None:
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

    async def _ended(self) -> None:
        """
        If message processing is finished, finalize processing this
        message. Otherwise do nothing.
        """
        if self._stream_in != S_END:
            return
        if self._stream_out != S_END:
            return
        await self.kill()

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

    def stream_in(self, *a, **kw) -> AbstractAsyncContextManager[Msg]:
        """
        Reply to a stream, read-only.
        """
        return self._stream(a, kw, SD_IN)

    def stream_out(self, *a, **kw) -> AbstractAsyncContextManager[Msg]:
        """
        Reply to a stream, write-only.
        """
        return self._stream(a, kw, SD_OUT)

    def stream(self, *a, **kw) -> AbstractAsyncContextManager[Msg]:
        """
        Reply to a stream, bidirectional.
        """
        return self._stream(a, kw, SD_BOTH)

    def _stream_call(self, flag: int) -> AbstractAsyncContextManager[Msg]:
        """
        Stream startup on the sending side.  Don't call this.
        """
        return self._stream((), None, flag, initial=True)

    @property
    def can_stream(self) -> bool:
        """check whether this is a streaming command"""
        if self._stream_in == S_END or self._stream_out == S_END:
            return False
        if self._stream_in != S_NEW or self._stream_out != S_NEW:
            return True
        if (rem := self.remote) is None:
            return False
        if not isinstance(rem, Msg):
            return False
        try:
            if rem._stream_in != S_NEW or rem._stream_out != S_NEW:  # noqa: SLF001
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
            res = cmd(*self._a, **self._kw)  # pyright:ignore
            if is_async(res):
                res = await res
        except Exception as exc:
            if self._remote is None:
                raise
            if not isinstance(exc, SilentRemoteError) and not isinstance(exc, ExpectedError):
                log_exc(exc, "Command Error %r", self)
            await self.ml_send_error(exc)
        except BaseException as exc:
            if self._remote is None:
                raise
            log_exc(exc, "Command Error %r", self)
            await self.ml_send_error(exc)
            raise
        else:
            if isinstance(res, Msg):
                await self.result(*res.args, **res.kw)  # pyright:ignore
            elif isinstance(res, MutableMapping):
                await self.result(**res)  # pyright:ignore
            else:
                await self.result(res)

    def ensure_remote(self):
        """
        A context mamager that adds a remote side to an existing message.
        """

        return _EnsureRemote(self)

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
            if not isinstance(exc, ExpectedError):
                log_exc(exc, "Stream Error %r", self)
            await self.ml_send_error(exc)
        except BaseException as exc:
            await self.ml_send_error(exc)
            raise

    def _stream(self, a: Sequence, kw: OptDict, flag: int, initial: bool = False):
        return _Stream(self, a, kw, flag, initial=initial)

    async def result(self, *a, **kw) -> None:
        """
        Send (or set) the result.
        """
        if self._remote is None:
            if self._msg is not None:
                if kw:
                    raise RuntimeError("Dup call", kw)
                if a and (len(a) > 1 or a[0] is not None):  # pyright:ignore
                    raise RuntimeError("Dup call", a)

            self._msg = outcome.Value((a, kw))
            self._msg_in.set()
            return

        await self.ml_send(a, kw, 0)

    async def wait_replied(self, preload: bool = False) -> None:
        """
        Wait for a (non-streamed) reply.
        """
        loaded, self._loaded = self._loaded, preload
        if loaded:
            return

        if self._msg is None:
            if self._stream_in == S_END:
                raise NoStream
            await self._msg_in.wait()
            self._msg_in = Event()
        msg = self._msg
        self._msg = self._msg2
        self._msg2 = None
        if msg is None:
            raise EOFError
        self._a, self._kw = msg.unwrap()  # pyright:ignore

    def __aiter__(self) -> Self:
        if not self._dir & SD_IN:
            raise RuntimeError("This stream is write only")
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
        assert self._recv_q is not None  # to shut up pyright

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
            raise StopAsyncIteration  # noqa:B904

        await self._qsize()
        return MsgResult(*res)

    def __repr__(self):
        return (
            f"<{self.__class__.__name__}:L{self.link_id} "
            f"r{'=L' + str(self._remote.link_id) if self._remote else '-'}: "
            f" {' ' + str(self._cmd) if self._cmd else ''} {self._a} {self._kw}>"
        )


class _Stream:
    def __init__(self, slf, a: Sequence, kw: OptDict | None, flag: int, initial: bool = False):
        self.slf = slf
        self.a = a
        self.kw = kw
        self.flag = flag
        self.initial = initial

    async def __aenter__(self):
        slf = self.slf
        if slf._stream_out != S_NEW:  # noqa: SLF001
            raise RuntimeError(
                "Simple command" if slf._stream_out == S_END else "Stream-out already set",  # noqa: SLF001
            )

        # stream-in depends on what the remote side sent
        await slf.prep_stream(self.flag)

        if slf._recv_qlen < 10:  # noqa: SLF001
            slf._fli = 0  # noqa: SLF001
            await slf.warn(slf._recv_qlen)  # noqa: SLF001

        if self.initial:
            await slf.wait_replied()
        else:
            await slf.ml_send(self.a, self.kw, B_STREAM, self.initial)
        return slf

    async def _close(self):
        # This code is running inside the handler, which will process the error
        # case. Thus we don't need error handling here.

        slf = self.slf
        if slf._stream_out != S_END:  # noqa: SLF001
            await slf.ml_send([None], {}, 0)

        await slf.wait_replied()
        if slf._stream_in != S_END:  # noqa: SLF001
            raise RuntimeError("Stream not ended")

    async def __aexit__(self, c, e, t):
        try:
            slf = self.slf
            if e is not None and slf._stream_out != S_END:  # noqa: SLF001
                await slf.ml_send_error(e)
            await self._close()
        finally:
            if e is not None:
                raise e


class _EnsureRemote:
    def __init__(self, slf):
        self.slf = slf

    async def __aenter__(self):
        slf = self.slf
        if (m := slf._remote) is None:  # noqa: SLF001
            m = Msg.Call(slf._cmd, slf._a, slf._kw)  # noqa: SLF001
            slf._cmd, slf._a, slf._kw = None, (), {}  # noqa: SLF001
            m.set_remote(slf)
            slf.set_remote(m)
        self.m = m
        return m

    async def __aexit__(self, *err):
        with shield():
            await self.m.kill()
            await self.slf.kill()
