"""
Stream link-up support for MoaT commands
"""

from __future__ import annotations

import sys

from moat.util import NotGiven, ValueEvent, obj2name
from moat.micro.cmd.base import BaseCmd
from moat.micro.cmd.util.valtask import ValueTask
from moat.micro.compat import AC_use, BaseExceptionGroup, L, TaskGroup, log
from moat.micro.errors import NoPathError, RemoteError, SilentRemoteError, StoppedError

# Typing
from typing import TYPE_CHECKING  # isort:skip

if TYPE_CHECKING:
    from typing import Any
    from collections.abc import Awaitable, Mapping

    from moat.micro.proto.stack import BaseMsg


class BaseCmdMsg(BaseCmd):
    """
    This is a command handler that relays arbitrary messages between MoaT's
    Cmd tree and a `BaseMsg` stream.

    The difference between this and a `BaseCmdBBM`-derived class is that
    this class encapsulates any message and requires a `BaseCmdMsg` handler
    on the other side to talk to.

    In contrast, a `BaseCmdBBM` exposes commands that directly access the underlying
    stream (of whatever type).
    """

    tg: TaskGroup = None

    def __init__(self, cfg):
        super().__init__(cfg)
        self.reply = {}
        self.seq = 2
        # locally-generated seqnums must be even
        # also we want them to not be zero
        # TODO: CBOR: use negative seqnums for replies
        #            instead of flipping the bottom bit

    async def stream(self) -> BaseMsg:
        """
        Creates the actual data stream.

        Must be overridden.
        """
        raise NotImplementedError("Create the stream: ", self.__class__.__name__)

    async def task(self):
        """
        Start the stack.

        You typically override `stream`, not this method.
        """
        try:
            await AC_use(self, self._cleanup_open_commands)
            self.s = await self.stream()
            async with TaskGroup() as self.tg:
                if L:
                    self.set_ready()
                while True:
                    msg = await self.s.recv()
                    await self._handle(msg)
        # DO NOT eat errors here, that interferes
        # with the sub.Err no-restart-on-success feature
        finally:
            self.s = None

    def _cleanup_open_commands(self):
        for e in self.reply.values():
            e.cancel()

    async def reply_result(self, i, res):
        "send the result back"
        if i is None:
            return
        try:
            await self.s.send({"i": i, "d": res})
        except Exception as e:  # pylint:disable=broad-exception-caught
            await self.reply_error(i, e)
        except BaseException as e:
            await self.reply_error(i, e)
            raise
        else:
            # reply_error also does this
            self.reply.pop(i, None)

    async def reply_error(self, i, exc, x=()):
        """
        Reply to message #@i with an error.

        Exception types in @x are expected and will not be logged.
        """
        res = NotGiven
        self.reply.pop(i, None)
        try:
            if isinstance(exc, (SilentRemoteError, OSError)):  # noqa:SIM114
                pass
            elif x and isinstance(exc, tuple(x)):
                pass
            elif i is None:
                log("ERROR handling <no-i>: %r", exc, err=exc)
            else:
                log("ERROR handling <%d>: %r", i, exc, err=exc)
            if i is None:
                return
            res = {"i": i}
            if isinstance(exc, Exception):
                try:
                    obj2name(type(exc))
                except KeyError:
                    res["e"] = "E:" + repr(exc)
                else:
                    res["e"] = type(exc)
                    res["d"] = exc.args
            else:
                res["e"] = StoppedError
                res["d"] = (repr(exc), "echo")
            await self.s.send(res)
        except TypeError as e2:
            log("ERROR returning %r", res, err=e2)
            await self.s.send({"e": "T:" + repr(e2), "i": i})

    async def _handle(self, msg):
        """
        Main handler for incoming messages
        """
        if not isinstance(msg, dict):
            print("?3", msg, file=sys.stderr)
            return
        a: tuple[str | int] | None = msg.get("a", None)  # action
        i: int | None = msg.get("i", None)  # seqnum
        d: Mapping[str, Any] | type[NotGiven] = msg.get("d", NotGiven)  # data
        e: type[Exception] | str = msg.get("e", None)  # error
        r: int | None = msg.get("r", None)  # repeat
        n: int | None = msg.get("n", None)  # iter_seq
        x: list[type[Exception]] = msg.get("x", ())  # exclude_error

        if i is not None:
            i ^= 1

        for k in msg.keys():
            if k not in "aidrenx":
                log("Unknown %s: %r", k, msg)
                break

        if a is not None:
            # incoming request
            # runs in a separate task
            # XXX create a task pool?
            if d is NotGiven:
                d = None
            if r is None:
                t = ValueTask(self, i, x, self.root.dispatch, a, d, x_err=x)
            else:
                if not L:
                    raise RuntimeError("not Large")
                from moat.micro.cmd.util.iter import SendIter

                t = SendIter(self, i, r, a, d)

            if i is not None:
                if i in self.reply:
                    log("msgid known?!? %d", i)
                    tt = self.reply.pop(i)
                    tt.i = None
                    r = tt.set_error(RuntimeError("OldCmd"))
                    if hasattr(r, "throw"):
                        await r

                self.reply[i] = t
            rm = await t.start(self.tg)
            if rm is not None:  # revised iterator rate
                await self.s.send({"i": i, "r": rm})

        else:
            # reply
            if i is None:
                log("?? %r", msg)
                return

            t = self.reply.get(i, None)
            if t is None:
                log("unknown %r", msg)
                return

            if e is not None:
                if isinstance(e, type):
                    if d is NotGiven:
                        d = ()
                    e = e(*d)
                elif isinstance(e, str):
                    e = RemoteError(e)
                elif isinstance(e, NoPathError):
                    e = e.prefixed(self.path)
                elif isinstance(e, Exception):
                    pass
                else:
                    log("unknown err %r", msg)
                    e = StoppedError(f"unknown {msg!r}")
                r = t.set_error(e)
                if hasattr(r, "throw"):
                    await r

            elif r is not None:
                if r is False:
                    r = t.set_error(StopAsyncIteration())
                    if hasattr(r, "throw"):
                        await r
                    del self.reply[i]
                else:
                    t.set_r(r)

            elif d is not NotGiven:
                if getattr(t, "_IT", False):
                    if n:
                        t.set(d, n=n)
                    else:
                        t.set(d)
                    return
                else:
                    t.set(d)
                    del self.reply[i]

            else:  # just i
                t.cancel()
                del self.reply[i]

    async def dispatch(
        self,
        action,
        msg=None,
        *,
        rep: int | None = None,
        wait=True,
        x_err=(),
    ):  # pylint:disable=arguments-differ
        """
        Forward a request to the remote side, return the response.

        The message is either the second parameter, or a dict (use any
        number of keywords).

        If @wait is False, the message doesn't have a sequence number and
        thus no reply will be expected.

        @rep requests iterated replies.
        """

        if len(action) == 1:
            a = action[0]
            if a[0] == "!":
                return await super().dispatch((a[1:],), msg, rep=rep, wait=wait, x_err=x_err)

        if L and await self.wait_ready():
            raise StoppedError("is down")  # already down

        if not wait:
            msg = {"a": action, "d": msg}
            await self.s.send(msg)
            return

        # Find a small-ish but unique *even* seqnum
        # even seqnums are requests from the other side
        if self.seq > 10 * (len(self.reply) + 5):
            self.seq = 10
        while True:
            seq = self.seq
            self.seq += 2
            if seq not in self.reply:
                break
        msg = {"a": action, "d": msg, "i": seq}
        if x_err:
            msg["x"] = x_err

        if rep:
            if L:
                from moat.micro.cmd.util.iter import RecvIter

                msg["r"] = rep
                self.reply[seq] = e = RecvIter(self, seq, rep)
                await self.s.send(msg)
                return e
            else:
                raise RuntimeError("not Large")
        else:
            self.reply[seq] = e = ValueEvent()
            try:
                await self.s.send(msg)
                return await e.get()
            finally:
                self.reply.pop(seq, None)

    async def cmd_crd(self, n=64) -> bytes:
        """read some console data"""
        b = bytearray(n)
        r = await self.s.crd(b)
        if r == n:
            return b
        elif r <= n >> 2:
            return bytes(b[:r])
        else:
            b = memoryview(b)
            return b[:r]

    async def cmd_cwr(self, b):
        """write some console data"""
        async with self.w_lock:
            await self.s.cwr(b)


class CmdMsg(BaseCmdMsg):
    """
    A baseCmdMsg with a ready-made link that it opens.
    """

    def __init__(self, link, cfg):
        super().__init__(cfg)
        self.link = link

    def stream(self) -> Awaitable[BaseMsg]:  # noqa:D102
        # pylint:disable=invalid-overridden-method
        return AC_use(self, self.link)


class SingleCmdMsg(BaseCmdMsg):
    """
    A BaseCmdMsg that disconnects on error, or when the connection ends,
    without propagating the exception.
    """

    # pylint:disable=abstract-method
    # `stream` needs to be implemented by a subclass

    async def run(self):  # noqa:D102
        # this would be far easier with "except*"
        # but µPy doesn't have that.
        try:
            try:
                await super().run()
            except BaseExceptionGroup as e:
                while True:
                    if len(e.exceptions) != 1:
                        a, b = e.split((EOFError, OSError, SilentRemoteError))
                        if a is not None:
                            log("Err %s: %r", self.path, repr(a))
                        if b is None:
                            return
                        raise b
                    e = e.exceptions[0]
                    if not isinstance(e, BaseExceptionGroup):
                        raise e  # noqa:TRY201
        except EOFError:
            pass
        except (OSError, SilentRemoteError) as exc:
            log("Err %s: %r", self.path, repr(exc))
        except Exception as exc:  # pylint:disable=broad-exception-caught
            log("Err %s", self.path, err=exc)


class ExtCmdMsg(SingleCmdMsg):
    """SingleCmdMsg, on a stream that was established externally.

    The caller is responsible for calling `wait_stopped`
    and then closing the stream!
    """

    def __init__(self, stream: BaseMsg, cfg: dict[str, Any] | None = None):
        if cfg is None:
            cfg = {}
        super().__init__(cfg)
        self.__s = stream

    async def stream(self):  # noqa:D102
        return await AC_use(self, self.__s)
