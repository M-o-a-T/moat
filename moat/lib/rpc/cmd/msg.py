"""
Stream link-up support for MoaT commands
"""

from __future__ import annotations

import sys

from moat.util import attrdict, merge
from moat.lib.codec.errors import SilentRemoteError
from moat.lib.micro import (
    AC_use,
    BaseExceptionGroup,  # noqa:A004
    L,
    Queue,
    TaskGroup,
    WouldBlock,
    idle,
    log,
)
from moat.lib.rpc import BaseCmd, HandlerStream

__all__ = ["BaseCmdMsg", "CmdMsg", "ExtCmdMsg", "MsgStream", "SharedIter", "SingleCmdMsg"]

# Typing
from typing import TYPE_CHECKING, cast  # isort:skip

if TYPE_CHECKING:
    from anyio.abc import CancelScope

    from moat.lib.micro import _TaskGroupProto
    from moat.lib.path import Path, PathElem
    from moat.lib.rpc import Auth, BaseMsgHandler, MsgSender
    from moat.lib.rpc.msg import Msg
    from moat.lib.stream import BaseMsg
    from moat.lib.stream.base import Buffer, MutBuffer

    from collections.abc import Mapping, Sequence
    from typing import Any, Protocol

    class _ConsoleMsgProto(Protocol):
        async def crd(self, buf: MutBuffer) -> int: ...

        async def cwr(self, buf: Buffer) -> None: ...


class SharedIter:
    """Fan-out wrapper for a remote iterator.

    This class allows multiple local consumers to share a single remote
    streaming command.  When the first subscriber attaches, the remote
    stream is opened; subsequent subscribers receive the same data via
    individual :class:`~moat.lib.micro.Queue` instances.  When the last
    subscriber detaches, the remote stream is closed.

    Args:
        sender: the :class:`~moat.lib.rpc.MsgSender` for reaching the remote side.
        path: the remote command path to subscribe to.
        tg: a :class:`~moat.lib.micro.TaskGroup` to spawn the reader task in.
        args: positional arguments for the remote call.
        kw: keyword arguments for the remote call.
    """

    _sender: MsgSender
    _path: Path
    _tg: _TaskGroupProto
    _args: tuple[Any, ...]
    _kw: Mapping[str, Any]
    _subs: set[Queue]
    _task: CancelScope | None = None

    def __init__(
        self,
        sender: MsgSender,
        path: Path,
        tg: _TaskGroupProto,
        *args: Any,
        **kw: Any,
    ):
        self._sender = sender
        self._path = path
        self._tg = tg
        self._args = args
        self._kw = kw
        self._subs = set()

    @property
    def subs(self) -> set[Queue]:
        """Currently-active subscriber queues."""
        return self._subs

    async def __aenter__(self) -> Queue:
        """Attach a new subscriber.

        Returns a :class:`Queue` from which the subscriber reads data.
        """
        q: Queue = Queue(10)
        self._subs.add(q)
        if self._task is None:
            # First subscriber: open the remote stream.
            self._task = await self._tg.spawn(self._reader)
        return q

    async def __aexit__(self, *tb: object) -> None:
        """Detach this subscriber's queue."""
        # The caller's queue is identified by being the smallest still-present;
        # since we don't track per-context, we rely on the caller closing it.
        # In practice, the subscriber's ``__aexit__`` closes their queue.
        pass

    def detach(self, q: Queue) -> None:
        """Remove a subscriber queue and close it."""
        self._subs.discard(q)
        q.close_sender()
        if not self._subs and self._task is not None:
            # Last subscriber gone: stop the reader task.
            task = self._task
            self._task = None
            try:
                task.cancel()  # type: ignore[union-attr]
            except RuntimeError:
                pass

    async def _reader(self) -> None:
        """Background task: read from the remote stream and fan out."""
        sender = self._sender
        try:
            cmd = sender.cmd(self._path, *self._args, **self._kw)
            async with cmd.stream_in() as st:
                async for data in st:
                    dead: list[Queue] = []
                    for q in self._subs:
                        try:
                            q.put_nowait(tuple(data.args))
                        except WouldBlock:
                            dead.append(q)
                    for q in dead:
                        self._subs.discard(q)
                        q.close_sender()
        except EOFError:
            pass
        except Exception as exc:
            if L:
                log("SharedIter %r: %r", self._path, exc)
            for q in list(self._subs):
                try:
                    q.put_nowait_error(exc)
                except WouldBlock:
                    pass
                q.close_sender()
        finally:
            self._task = None
            for q in list(self._subs):
                q.close_sender()
            self._subs.clear()


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
    __rprefix: tuple[PathElem, ...] = ()
    stream_owner_obj_: object
    _shared: dict[tuple[PathElem, ...], SharedIter] | None = None

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
                    self.auth.update(tcfg)  # ty:ignore[attr-defined]
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

    def auth_data_in(self, args: Sequence, data: Mapping[str, Any]) -> None:
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

    def auth_data_res_in(self, role: str, data: Mapping[str, Any]) -> None:
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
        "also cancel auth and shared iterators"
        self.auth_stop()
        # Cancel any active shared iterators.
        shared = self._shared
        if shared is not None:
            self._shared = None
            for si in list(shared.values()):
                for q in list(si.subs):
                    si.detach(q)
        await super().teardown()

    async def stream(self) -> BaseMsg:
        """
        This method creates (and returns) the data stream.

        Must be overridden.

        Cleanup is typically handled via `moat.lib.micro.AC_use`.
        """
        raise NotImplementedError("Create the stream: ", self.__class__.__name__)

    async def setup(self):
        "Sets ``__rprefix`` and creates the shared-iterator task group."
        await super().setup()

        rprefix = self.cfg.get("prefix", {}).get("send", ())
        if rprefix:
            rprefix = list(rprefix)
            rprefix.reverse()
            self.__rprefix = rprefix  # ty:ignore[invalid-assignment]

        # Create a task group for shared-iterator reader tasks.
        self.tg = await AC_use(self, TaskGroup())

    async def task(self):
        """
        Start the MsgStream.
        """
        root0 = self.root
        if root0 is None:
            raise RuntimeError("Not attached")
        root = root0.sender
        lprefix = self.cfg.get("prefix", {}).get("recv", ())
        if lprefix:
            root = root.sub_at(lprefix)

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

    doc_mon_ = dict(
        _d="Subscribe to a shared remote iterator",
        _0="path:remote command path",
        _o="data from the remote iterator",
    )

    async def stream_mon_(self, msg: Msg):
        """Stream data from a shared remote iterator.

        The first caller for a given path opens the remote stream;
        subsequent callers receive the same data.  When the last
        subscriber disconnects, the remote stream is closed.

        Args:
            msg[0]: the remote command path to subscribe to.
        """
        from moat.lib.path import Path  # noqa: PLC0415

        path = msg.get(0)
        if path is None:
            raise KeyError("path required")
        if not isinstance(path, Path):
            path = Path.build((path,))

        # Remaining args/kwargs are forwarded to the remote command.
        rem_args = tuple(msg.args[1:])
        rem_kw = dict(msg.kw) if msg.kw else {}

        root = self.root
        if root is None:
            raise RuntimeError("Not attached")
        sender = root.sender

        # Apply the send prefix, if any.
        sprefix = self.cfg.get("prefix", {}).get("send", ())
        if sprefix:
            sender = sender.sub_at(sprefix)

        # Lazily create a task group for shared-iterator reader tasks.
        tg = self.tg
        if tg is None:
            raise RuntimeError("No task group")

        if self._shared is None:
            self._shared = {}
        key = tuple(path)
        si = self._shared.get(key, None)
        if si is None:
            si = SharedIter(sender, path, cast("_TaskGroupProto", tg), *rem_args, **rem_kw)
            self._shared[key] = si

        async with msg.stream_out() as st:
            q = await si.__aenter__()
            try:
                while True:
                    try:
                        data = await q.get()
                    except EOFError:
                        break
                    await st.send(*data)
            finally:
                si.detach(q)
                if not si.subs and key in self._shared:
                    del self._shared[key]


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
