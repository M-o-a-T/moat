"""
Stream link-up support for MoaT commands
"""

from __future__ import annotations

from moat.util import merge
from moat.lib.cmd.errors import NotReadyError
from moat.lib.cmd.stream import HandlerStream
from moat.lib.codec.errors import SilentRemoteError
from moat.micro.cmd.base import BaseCmd
from moat.util.compat import AC_use, BaseExceptionGroup, L, TaskGroup, idle, log  # noqa:A004

# Typing
from typing import TYPE_CHECKING  # isort:skip

if TYPE_CHECKING:
    from moat.lib.cmd import MsgSender
    from moat.micro.proto.stack import BaseMsg

    from collections.abc import Awaitable
    from typing import Any


class MsgStream(HandlerStream):
    """
    This :moat.lib.cmd.stream:`HandlerStream` subclass
    interfaces with a `BaseCmdMsg` stream.

    """

    def __init__(self, handler: MsgSender, stream: BaseCmdMsg):
        self.__stream = stream
        super().__init__(handler)

    async def read_stream(self):
        "Background stream reader. Started from the HandlerStream context manager."
        str = self.__stream  # noqa: A001
        while True:
            msg = await str.recv()
            await self.msg_in(msg)

    async def write_stream(self):
        "Background stream writer. Started from the HandlerStream context manager."
        str = self.__stream  # noqa: A001
        while True:
            msg = await self.msg_out()
            await str.send(msg)


class BaseCmdMsg(BaseCmd):
    """
    This is a command handler that relays arbitrary messages between MoaT's
    Cmd tree and a `BaseMsg` stream.

    The difference between this and a
    :moat.micro.cmd.stream:`BaseCmdBBM`-derived class is that this class
    encapsulates arbitrary message/stream calls and requires a `BaseCmdMsg`
    handler on the other side to talk to.

    In contrast, a :moat.micro.cmd.stream:`BaseCmdBBM` exposes commands
    that directly read or write the underlying stream (of whatever type).

    This class cannot wrap a pre-existing stream, by design.
    """

    tg: TaskGroup = None
    __stream = None

    def __init__(self, cfg):
        super().__init__(cfg)

    doc = dict(_d="Foo")

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
        # Handle local commands (and documentation) locally
        if (
            (len(rcmd) == 1 or (len(rcmd) == 2 and rcmd[1] == "doc_"))
            and rcmd[0] != "dir_"
            and (hasattr(self, f"cmd_{rcmd[0]}") or hasattr(self, f"stream_{rcmd[0]}"))
        ):
            return await super().handle(msg, rcmd)

        if rcmd and rcmd[0] == "rdy_":
            if await self.wait_ready(wait=True):
                raise NotReadyError(msg.cmd, rcmd)
        if self.__stream is None:
            raise EOFError

        # forward to remote
        res = await self.__stream.handle(msg, rcmd)

        # if it was a directory request, add local data
        if len(rcmd) == 1 and rcmd[0] == "dir_":
            # Merge local commands into the remote ones
            m2 = await self.cmd_dir_(v=msg.get("v", True))
            await msg.wait_replied(preload=True)

            msg._kw["c"] = tuple(set(msg.get("c", ())) | set(m2.pop("c", ())))  # noqa: SLF001
            msg._kw["s"] = tuple(set(msg.get("s", ())) | set(m2.pop("s", ())))  # noqa: SLF001
            merge(msg._kw, m2)  # noqa: SLF001
        return res

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
                        raise b  # noqa:B904,RUF100
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
