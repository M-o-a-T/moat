"""
Stream link-up support for MoaT commands
"""

from __future__ import annotations

import sys

from moat.util import NotGiven, ValueEvent
from moat.lib.codec.proxy import obj2name
from moat.micro.cmd.base import BaseCmd
from moat.lib.cmd.stream import HandlerStream
from moat.micro.cmd.util.valtask import ValueTask
from moat.util.compat import AC_use, BaseExceptionGroup, L, TaskGroup, log, idle
from moat.lib.codec.errors import NoPathError, RemoteError, SilentRemoteError, StoppedError

# Typing
from typing import TYPE_CHECKING  # isort:skip

if TYPE_CHECKING:
    from typing import Any
    from collections.abc import Awaitable, Mapping

    from moat.micro.proto.stack import BaseMsg


class MsgStream(HandlerStream):
    "Stream handler subclass for `BaseCmdMsg`."

    def __init__(self, handler: MsgSender, stream: BaseCmdMsg):
        self.__stream = stream
        super().__init__(handler)

    async def read_stream(self):
        str = self.__stream
        while True:
            msg = await str.recv()
            await self.msg_in(msg)

    async def write_stream(self):
        str = self.__stream
        while True:
            msg = await self.msg_out()
            await str.send(msg)


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
            self.s = await self.stream()
            async with MsgStream(self.root, self.s) as st:
                self.__stream = st
                if L:
                    self.set_ready()
                await idle()

        finally:
            self.s = None
            self.__stream = None

    async def reply_result(self, i, res):
        "send the result back"
        if i is None:
            return
        try:
            await self.s.send({"i": i, "d": res})
        except Exception as e:
            await self.reply_error(i, e)
        except BaseException as e:
            await self.reply_error(i, e)
            raise

    async def handle(self, msg, rcmd) -> Awaitable[Any]:
        """
        Forward a request to some remote side.
        """
        if (len(rcmd) == 1 or len(rcmd) == 2 and rcmd[1] == "doc_") and rcmd[0] in {"crd", "cwr"}:
            pass
        elif rcmd and isinstance(rcmd[-1], str) and rcmd[-1][0] == "!":
            rcmd[-1] = rcmd[-1][1:]
        elif self.__stream is None:
            raise EOFError
        else:
            return await self.__stream.handle(msg, rcmd)
        return await super().handle(msg, rcmd)

    doc_crd = dict(_d="read console", _0="int:len (64)")

    async def cmd_crd(self, n=64) -> bytes:
        """read some console data"""
        b = bytearray(n)
        if self.s is None:
            raise EOFError
        r = await self.s.crd(b)
        if r == n:
            return b
        elif r <= n >> 2:
            return bytes(b[:r])
        else:
            b = memoryview(b)
            return b[:r]

    doc_cwr = dict(_d="write console", _0="bytes:data")

    async def cmd_cwr(self, b):
        """write some console data"""
        async with self.w_lock:
            if self.s is None:
                raise EOFError
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
