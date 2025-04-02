"""
Basic message block
"""

from moat.util.compat import log, Event
from ._base import MsgRemote

from typing import TYPE_CHECKING, overload
if TYPE_CHECKING:
    from typing import Self


class Msg(MsgRemote):
    """
    Message encapsulation and data streaming.
    """
    _cmd:Path|None = None
    _a:list|None = None
    _kw:dict|None = None

    _stream_in:int = S_NEW
    _stream_out:int = S_NEW

    _dir:int = SD_NONE

    _msg_in:Event

    def __init__(self):
        """
        Set up the message.
        """
        self._msg_in = Event()

    @property
    def cmd(self) _> Path:
        "Retrieve the command."
        return self._cmd

    @property
    def args(self):
        "Retrieve the argument list."
        return self._args

    def __len__(self):
        return len(self._args)

    def __bool__(self):
        return True

    @property
    def kw(self):
        "Retrieve the keywords."
        return self._kw


    @classmethod
    def Call(cls, cmd:Path,a:list,kw:dict) -> Self:
        """Constructor for a possibly-remote function call."""
        s = cls()
        s._cmd = cmd
        s._a = a
        s._kw = kw
        return s

    @property
    def remote(self):
        return self._remote

    def set_remote(self, remote):
        if self._stream_in != S_NEW:
            raise RuntimeError("incoming already started")
        if self._stream_out != S_NEW:
            raise RuntimeError("outgoing already started")
        super().set_remote(remote)

    def emplace(self, remote:MsgRemote):
        """Change the remote's remote to me"""
        if self._remote is None:
            # we are a straight command handler and don't yet have a remote.
            self.set_remote(remote)
            remote.set_remote(self)
            return

        rrem = remote.remote
        if rrem is not None:
            rrem.kill(new=True)

        remote.set_remote(self)
        self.set_remote(remote)

    def kill(self, new:bool=False):
        """No further communication may happen.

        If @new is set, this not being a "new" stream will raise an error.
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

    @property
    def can_stream(self):
        """
        Check if this is a streaming command
        """
        return self._stream_in != S_END

    def recv(self, a:list,kw:dict,flags:int) -> None:
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
            logger.warning("LATE? %r %r %d", a,kw,flags)

        elif not (flags&B_STREAM):
            self._set_msg(a,kw,flags)
            self._stream_in = S_END
            if self._recv_q is not None:
                self._recv_q.close_sender()

        elif flags&B_ERR:
            exc = StreamError(a,kw)
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
            elif self._stream_in == S_ON and self._recv_q is not None:
                self._recv_q.put_nowait_error(exc)
            else:
                self.warn.append(exc)

        elif self._stream_in == S_NEW:
            self._set_msg(a,kw,flags)

        elif self._recv_q is not None:
            try:
                self._recv_q.put_nowait((a,kw))
            except QueueFull:
                self._recv_skip = True

        else:
            log("Unwanted stream: %r/%r/%d", a,kw,flags)
            if self._stream_in == S_ON:
                self._stream_in = S_OFF
                if self._stream_out != S_END:
                    self.ml_send([E_NO_STREAM], None, B_ERROR)
                    self._stream_out = S_END

        self._ended()

    def _set_msg(self, a:list,kw:dict, flags:int):
        """
        A message has arrived on this stream. Store and set an event.
        """
        if self._stream_in == S_END:
            pass  # happens
        else:
            self._initial = bool(flags&B_INITIAL)
            if not (flags&B_STREAM):
                self._stream_in = S_END
            elif self._stream_in == S_NEW and not err:
                self._stream_in = S_ON

        if flags&B_ERR:
            self._msg = outcome.Error(StreamError(msg[1:]))
        else:
            self._msg = outcome.Value((a,kw))
        self._msg_in.set()
        if self._stream_in != S_END:
            self._msg_in = Event()
        else:
            self._ended()

    # Stream starters

    def prep_stream(self, flag:int) -> None:
        """Sets up streaming as per SD_* flags"""
        self._dir = flag

        if flag & SD_IN:
            self._recv_q = Queue(self.qlen)


    async def no_stream(self):
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

    @property
    def can_stream(self) -> bool:
        """check whether this is a streaming command"""
        return self._stream_out != S_NEW

    async def call_simple(self, cmd:Callable) -> None:
        try:
            res = cmd(*self._a, **self._kw)
            if hasattr(res,"__await__"):
                res = await res
        except Exception as exc:
            log("Command Error %r %r",self,exc)
            self.ml_send([exc.__class__.__name__]+exc.args, None, B_ERROR)
        except BaseException as exc:
            log("Command Error %r %r",self,exc)
            self.ml_send([exc.__class__.__name__]+exc.args, None, B_ERROR)
            raise
        else:
            self.result(res)

    async def call_stream(self, cmd:Callable) -> None:
        try:
            await cmd(*self._a,**self._kw)
        except Exception as exc:
            log("Command Error %r %r",self,exc)
            self.ml_send([exc.__class__.__name__]+exc.args, None, B_ERROR)
        except BaseException as exc:
            log("Command Error %r %r",self,exc)
            self.ml_send([exc.__class__.__name__]+exc.args, None, B_ERROR)
            raise


    @asynccontextmanager
    async def _stream(self, a:list, kw:dict, flag:int):
        if self._stream_out != S_NEW:
            raise RuntimeError(
                "Simple command" if self._stream_out == S_END else "Stream-out already set",
            )

        # stream-in depends on what the remote side sent
        if not (flag & SD_IN):
            q, self._recv_q = self._recv_q, None
            if q is not None and q.qsize() and self._stream_in == S_ON:
                self._stream_in = S_OFF
                await self.warn(E_NO_STREAM)
            # whatever has been received will be discarded

        self._dir = flag

        if self._recv_qlen < 10:
            self._fli = 0
            await self.warn(self._recv_qlen)

        await self.ml_send(a, kw, B_STREAM)
        if self._i >= 0:
            # Wait for the initial reply if we're the sender.
            await self.replied()

        yield self

        # This code is running inside the handler, which will process the error
        # case. Thus we don't need error handling here.

        if self._stream_out != S_END:
            await self.ml_send([None])

        if self._stream_in == S_END:
            pass
        else:
            self._msg = None
            await self.replied()

    def result(self, *a, **kw) -> None:
        """
        Send (or set) the result.
        """
        if self._remote is None:
            self.a = a
            self.kw = kw
            self._msg_in.set()
            return
        self.ml_send(a, kw, 0)

    async def wait_replied(self) -> None:
        """
        Wait for a (non-streamed) reply.
        """
        await self._msg_in.wait()

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



