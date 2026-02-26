"""
Stream link-up support for MoaT commands
"""

from __future__ import annotations

import sys

from moat.util import attrdict, merge
from moat.lib.codec.errors import SilentRemoteError
from moat.lib.micro import AC_use, BaseExceptionGroup, L, TaskGroup, idle, log  # noqa:A004
from moat.lib.rpc import BaseCmd, HandlerStream, MsgSender

__all__ = ["BaseCmdMsg", "CmdMsg", "ExtCmdMsg", "MsgStream", "SingleCmdMsg"]

# Typing
from typing import TYPE_CHECKING, cast  # isort:skip

if TYPE_CHECKING:
    from moat.lib.path import PathElem
    from moat.lib.rpc import Auth, BaseMsgHandler
    from moat.lib.rpc.msg import Msg
    from moat.lib.stream import BaseMsg
    from moat.lib.stream.base import Buffer, MutBuffer

    from collections.abc import Sequence
    from typing import Any, Protocol

    class _ConsoleMsgProto(Protocol):
        async def crd(self, buf: MutBuffer) -> int: ...

        async def cwr(self, buf: Buffer) -> None: ...


class MsgStream(HandlerStream):
    """
    This :moat.lib.rpc.stream:`HandlerStream` subclass
    interfaces with a `BaseCmdMsg` stream.

    """

    def __init__(self, handler: BaseMsgHandler, stream: BaseMsg):
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
    This is a command handler that relays arbitrary MoaT-RPC messages
    and a `~moat.lib.stream.BaseMsg`-compatible stream.

    The difference to `~moat.lib.rpc.stream.cmdbbm.BaseCmdBBM` is that this
    class encapsulates arbitrary message/stream calls and requires a
    `~moat.lib.rpc.cmd.msg.BaseCmdMsg` handler on the other side to talk to.

    In contrast, a `~moat.lib.rpc.stream.cmdbbm.BaseCmdBBM` exposes commands
    that directly read or write the underlying stream (of whatever type).

    This class cannot wrap a pre-existing stream. Its :meth:`stream` method
    **must** be overridden to create the stream.

    Parameters:
        prefix.recv(Path): Prefix for incoming messages
        prefix.send(Path): Prefix for outgoing messages

    If the configuration has an ``auth`` item, this will redirect
    all messages through a :py.cls:`~moat.lib.rpc.Auth` instance.
    """

    tg: object | None = None
    __stream = None
    __rprefix = ()
    stream_owner_obj_: object

    doc = dict(_d="Foo")
    auth: attrdict | None = None
    is_server: bool = False
    _auth: Auth | None = None

    auth_name: str | None = None

    def __init__(self, cfg, *, is_server: bool = False, **kw):
        self.is_server = is_server
        super().__init__(cfg, **kw)
        if "auth" in cfg:
            from moat.lib.rpc import Auth  # noqa:PLC0415

            self.auth = attrdict()
            if "pytest" in sys.modules:
                tcfg = cfg.auth.get("test", None)
                if tcfg is not None:
                    self.auth.update(tcfg)
            self._auth = Auth(cfg.auth, self)

    @property
    def auth_helper(self) -> Auth | None:
        "Getter."
        return self._auth

    def auth_stop(self) -> None:
        """
        Stop auth processing.

        This does not remove the auth handler due to security
        considerations.
        """
        if self._auth is None:
            return
        self._auth.stop()

    def auth_data_out(self) -> dict:
        """
        Generates data for the outgoing auth message.

        Called on auth startup.
        """
        return {}

    def auth_data_in(self, args: Sequence, data: dict) -> None:
        """
        Data from the incoming auth message.
        """
        args  # noqa:B018
        data  # noqa:B018
        pass

    def auth_data_res_out(self, role: str) -> dict:
        """
        Generates data for the outgoing auth acknowledgment.

        Called after auth is complete.

        Args:
            role: the auth method that succeeded.
        """
        role  # noqa:B018
        return {}

    def auth_data_res_in(self, role: str, data: dict) -> None:
        """
        Data from the incoming auth acknowledgment.

        Args:
            role: the auth method that succeeded on the remote side.
            data: other data that the remote side returned.
        """
        pass

    def auth_skip(self) -> None:
        """
        Callback to signal that auth did not take place because the other
        side doesn't support it.
        """
        pass

    async def wait_for_auth(self):
        "wait for auth to complete"
        if self._auth is not None:
            await self._auth.wait_done()

    def stream_owner_(self):
        """Owner for stream contexts opened by :meth:`stream`.

        Auth temporarily overrides this so transport-layer contexts opened in
        ``process()`` are closed before the auth taskgroup exits.
        """
        return getattr(self, "stream_owner_obj_", self)

    async def teardown(self):
        "also cancel auth"
        self.auth_stop()
        await super().teardown()

    async def stream(self) -> BaseMsg:
        """
        This method creates (and returns) the data stream.

        Must be overridden.

        Cleanup is typically handled via `moat.lib.micro.AC_use`.
        """
        raise NotImplementedError("Create the stream: ", self.__class__.__name__)

    async def setup(self):
        "Sets ``__rprefix``"
        await super().setup()

        rprefix = self.cfg.get("prefix", {}).get("send", ())
        if rprefix:
            rprefix = list(rprefix)
            rprefix.reverse()
            self.__rprefix = rprefix

    async def task(self):
        """
        Start the MsgStream.
        """
        root = self.root.sender
        lprefix = self.cfg.get("prefix", {}).get("recv", ())
        if lprefix:
            root = cast(MsgSender, root.sub_at(lprefix))

        if self._auth:
            await self._auth.process(root)
        else:
            await self.process(root)

    async def process(self, root: BaseMsgHandler):
        """
        Low-level handler to run the message processor.

        Args:
            root: The MsgSender to route incoming commands to.

        The stream to use is retrieved by calling :py.meth:`stream`.
        """
        try:
            self.s = await self.stream()
            async with MsgStream(root, self.s) as st:
                self.__stream = st
                if L:
                    self.set_ready()
                await idle()

        finally:
            self.s = None
            self.__stream = None

    async def handle(
        self, msg: Msg, rcmd: list[PathElem], *prefix: str, _auth: bool = False
    ) -> Any:
        """
        Forward a request to some remote side.
        """
        prefix  # noqa:B018
        # If auth, route through it.
        if self._auth and not _auth:
            return await self._auth.handle(msg, rcmd)

        # Handle local commands (and documentation) locally
        if (
            (len(rcmd) == 1 or (len(rcmd) == 2 and rcmd[1] == "doc_"))
            and rcmd[0] != "dir_"
            and (hasattr(self, f"cmd_{rcmd[0]}") or hasattr(self, f"stream_{rcmd[0]}"))
        ):
            return await super().handle(msg, rcmd)

        await self.check_rdy(msg, rcmd)
        if self.__stream is None:
            raise EOFError

        # forward to remote
        rcmd.extend(self.__rprefix)
        res = await self.__stream.handle(msg, rcmd)

        # if it was a directory request, add local data
        if len(rcmd) == 1 and rcmd[0] == "dir_":
            # Merge local commands into the remote ones
            m2 = await self.cmd_dir_(v=msg.get("v", True))
            await msg.wait_replied(preload=True)

            if msg._kw is None:  # noqa: SLF001
                msg._kw = {}  # noqa: SLF001
            kw = cast(dict, msg._kw)  # noqa: SLF001
            kw["c"] = tuple(set(msg.get("c", ())) | set(m2.pop("c", ())))
            kw["s"] = tuple(set(msg.get("s", ())) | set(m2.pop("s", ())))
            merge(kw, m2)
        return res

    doc_crd = dict(_d="read console", _0="int:len (64)")

    async def cmd_crd(self, n=64) -> Buffer:
        """read some console data"""
        b = bytearray(n)
        if self.s is None:
            raise EOFError
        s = cast("_ConsoleMsgProto", self.s)
        r = await s.crd(b)
        if r == n:
            return b
        elif r <= n >> 2:
            return bytes(b[:r])
        else:
            b = memoryview(b)
            return b[:r]

    doc_cwr = dict(_d="write console", _0="bytes:data")

    async def cmd_cwr(self, b: Buffer):
        """write some console data"""
        if self.s is None:
            raise EOFError
        await cast("_ConsoleMsgProto", self.s).cwr(b)

    doc_c = dict(
        _d="r/w console stream", _0="int:rdbuflen (64)", _i="bytes:to send", _o="bytes:received"
    )

    async def stream_c(self, msg):
        "read/write console stream"
        n = msg.get(0, 64)
        async with msg.stream() as st, TaskGroup() as tg:

            @tg.start_soon
            async def crd():
                while True:
                    await st.send(await self.cmd_crd(n))

            async for m in st:
                await self.cmd_cwr(m[0])
            tg.cancel()


class CmdMsg(BaseCmdMsg):
    """
    A baseCmdMsg with a ready-made link that it opens.
    """

    def __init__(self, cfg: dict, link: BaseMsg):
        super().__init__(cfg)
        self.link = link

    async def stream(self) -> BaseMsg:  # noqa:D102
        # pylint:disable=invalid-overridden-method
        return await AC_use(self.stream_owner_(), self.link)


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

    The caller is responsible for calling :meth:`~moat.lib.rpc.BaseCmd.wait_stopped`
    and then closing the stream!
    """

    def __init__(self, cfg: dict[str, Any], stream: BaseMsg, *, is_server: bool = False):
        if cfg is None:
            cfg = {}
        super().__init__(cfg, is_server=is_server)
        self.__s = stream

    async def stream(self):  # noqa:D102
        return await AC_use(self.stream_owner_(), self.__s)
