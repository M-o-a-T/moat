"""
The MoaT-Link client
"""

from __future__ import annotations

import anyio
import logging
import os
import platform
import sys
import time
from contextlib import asynccontextmanager, nullcontext, suppress
from contextvars import ContextVar
from functools import partial
from traceback import format_exception

import outcome
from attrs import define, field
from mqttproto import QoS, RetainHandling

from moat.util import (
    CtxObj,
    NotGiven,
    P,
    Path,
    PathLongener,
    Root,
    ValueEvent,
    attrdict,
    ctx_as,
    gen_ident,
    srepr,
    timed_ctx,
    ungroup,
)
from moat.lib.cmd.base import Caller, MsgSender
from moat.util.random import al_unique

from .auth import AnonAuth, TokenAuth
from .common import CmdCommon
from .conn import TCPConn, UnixConn
from .exceptions import AuthError, ClientCancelledError
from .hello import Hello
from .meta import MsgMeta
from .node import Node

from typing import TYPE_CHECKING, overload

if TYPE_CHECKING:
    from contextlib import AbstractAsyncContextManager

    from moat.lib.cmd.base import MsgHandler
    from moat.lib.cmd.msg import Msg
    from moat.link.node.codec import CodecNode

    from .backend import Message
    from .schema import Data
    from .schema import SchemaName as S

    from collections.abc import AsyncIterator, Awaitable
    from typing import Any, Literal


class _Requeue(Exception):
    pass


__all__ = ["BasicLink", "Link", "LinkCommon", "get_link"]

_the_link = ContextVar("_the_link")

local_addrs = {"localhost", "127.0.0.1", "::1"}


def get_link() -> Link | None:
    """
    Return the global Link instance, if one exists.
    """
    return _the_link.get(None)


class TS(anyio.abc.TaskStatus):
    "A wrapper to TaskStatus that swallows successive calls"

    def __init__(self, ts):
        self.ts = ts

    def started(self, data=None):
        "call .started once"
        self.ts.started(data)
        self.ts = anyio.TASK_STATUS_IGNORED


class BasicCmd:
    """
    A simple command that doesn't require streaming.

    The command can thus be repeated if a connection dies while it's
    running.
    """

    def __init__(self, a, kw):
        self.a = a
        self.kw = kw
        self._result = None
        self._evt = anyio.Event()

    async def run(self, link):
        "run the command"
        try:
            res = await link.cmd(*self.a, **self.kw)
        except anyio.get_cancelled_exc_class():
            raise
        except Exception as exc:
            self._result = outcome.Error(exc)
        else:
            self._result = outcome.Value(res)
        finally:
            self._evt.set()

    @property
    async def result(self):
        "retreve the result"
        await self._evt.wait()
        if self._result is None:
            raise _Requeue
        return self._result.unwrap()


class LinkCommon(CmdCommon):
    """
    Common code for links to MQTT only (BasicLink) and to a MoaT-Link server (Link).
    """

    protocol_version: int = -1
    name: str
    server_name: str
    is_server: bool = False

    def __init__(self, cfg, name: str | None = None):
        self.cfg = cfg
        self._id = gen_ident(12, alphabet=al_unique)
        if name is not None:
            self.is_server = True
        else:
            name = cfg.get("client_id")
            if name is None:
                name = "_" + self._id
        self.name = name

        self._cmdq_w, self._cmdq_r = anyio.create_memory_object_stream(5)
        self.logger = logging.getLogger(f"moat.link.client.{name}")
        self.sender = MsgSender(self)

    def handle(self, msg, rpath, *add) -> Awaitable[Any]:
        """
        Message handler that intercepts incoming commands
        while authorization has not completed
        """
        if self._hello is not None and self._hello.auth_data is None:
            return self._hello.handle(msg, rpath, *add)

        return super().handle(msg, rpath, *add)

    @property
    def id(self):  # noqa:D102
        return self._id

    async def _connected_port(self, *, task_status=anyio.TASK_STATUS_IGNORED):
        async with self._connect_one(self._port) as hdl:
            task_status.started(hdl)
            await anyio.sleep_forever()

    @asynccontextmanager
    async def _connect_one(self, remote: dict | str, data: dict | None = None) -> MsgHandler:
        auth_out = []
        if isinstance(remote, dict):
            with suppress(KeyError):
                auth_out.append(TokenAuth(data["auth"]["token"]))
            conn_ = TCPConn(
                self, remote_host=remote["host"], remote_port=remote["port"], logger=self.logger
            )
        else:
            conn_ = UnixConn(self, path=remote, logger=self.logger.debug)

        auth_out.append(AnonAuth())
        self._hello = Hello(me=self.name, me_server=self.is_server, auth_out=auth_out)
        yielded = False

        async with conn_ as conn:
            if self.logger.isEnabledFor(logging.INFO):
                self.logger.info("Connection %s to %s", self.name, srepr(remote))
            handler = MsgSender(conn)
            if (res := await self._hello.run(handler)) is False:
                raise AuthError("Initial handshake failed")

            if isinstance(res, dict):
                name = res.pop("name", None)
                if name is not None:
                    self.name = name
                if res:
                    self.logger.warning("Unknown auth reply: %r", res)

            self.name = self._hello.me
            self.server_name = self._hello.them
            self.protocol_version = self._hello.protocol_version
            self._hello = None  # done with that

            yielded = True
            yield handler

        if not yielded:
            raise EOFError


class ClientCaller(Caller):  # nqa:D102
    def __init__(self, sender, *a, **kw):
        self._link = sender._link  # noqa:SLF001
        super().__init__(sender, *a, **kw)

    @asynccontextmanager
    async def _ctx(self):
        await self._link.get_link()
        async with super()._ctx() as res:
            yield res

    async def _call(self):
        "helper for __await__ that calls the remote handler"
        link = await self._link.get_link()
        cmd, a, kw = self.data
        return await link.root._sender.cmd(cmd, *a, **kw)  # noqa:SLF001


class LinkSender(MsgSender):
    """
    This is the client-side front-end to a "standard" MoaT-Link connection.

    It contains various somewhat-high-level helpers. Most are named like
    the corresponding backend commands, with an underscore replacing the
    dot.
    """

    Caller_ = ClientCaller

    _codec_tree: CodecNode | None = None

    def __init__(self, link: LinkCommon):
        self._link = link
        self.announced = self._link.announced

    @property
    def root(self):
        return self

    @property
    def link(self):
        return self._link

    @property
    def name(self) -> str:
        return self._link.name

    @property
    def cfg(self) -> attrdict:
        return self._link.cfg

    @property
    def id(self) -> str:
        return self._link.id

    async def handle(self, msg: Msg, rcmd: list) -> Awaitable[None]:
        """
        Standard handler, forwards to the remote side.
        """
        srv = await self._link.get_link()
        await srv.handle(msg, rcmd)

    def find_handler(self, path, cmd: bool = False) -> tuple[MsgHandler, Path]:
        """
        Standard sub-dispatcher redirector, no-op.
        """
        cmd  # noqa:B018
        return self, path

    @asynccontextmanager
    async def announcing(self, *a, **kw):
        """
        Frontend for `moat.link.announce.announcing`.
        """
        from moat.link.announce import announcing as ann  # noqa:PLC0415

        async with ann(self, *a, **kw) as res:
            yield res

    @overload
    def d_get(self, path: Path, meta: Literal[True]) -> tuple[Any, MsgMeta]: ...

    @overload
    def d_get(self, path: Path) -> Any: ...

    async def d_get(self, path: Path, meta: bool = False) -> tuple[Any, MsgMeta]:
        """
        Data retrieval. Calls the server's ``d.get`` method.

        Returns a data+metadata tuple if @meta is True, otherwise just the
        data.
        """
        if len(path) and isinstance(path[0], Path):
            raise ValueError("Don't use a root-prefixed path here.")

        res = await self.d.get(path)
        if not meta:
            return res[0]
        return res[0], MsgMeta.restore(res[1:])

    @overload
    async def d_set(
        self,
        path: Path,
        data: Any = NotGiven,
        t: float | None = None,
        meta: Literal[True] = True,
        retain: bool | None = None,
    ) -> tuple[Any, MsgMeta]: ...

    @overload
    async def d_set(
        self,
        path: Path,
        data: Any = NotGiven,
        t: float | None = None,
        meta: Literal[False] = False,
        retain: bool | None = None,
    ) -> None: ...

    async def d_set(
        self,
        path: Path,
        data: Any = NotGiven,
        meta: MsgMeta | None = None,
        t: float | None = None,
        with_prev: bool = False,
        retain: bool | None = None,
    ) -> None | tuple[Any, MsgMeta]:
        """
        Data update.

        If a timestamp is passed in @t or the old value+metadata is
        requested via @with_prev, goes through the server. Otherwise posts to
        MQTT directly.
        """
        if path and isinstance(path[0], Path):
            raise ValueError("Don't use a root-prefixed path here.")

        if meta is None:
            meta = MsgMeta(origin=self._link.name)
        if t is None and not with_prev:
            if retain is None:
                retain = len(path) == 0 or path[0] != "run"
            await self.send(Root.get() + path, data=data, meta=meta, retain=retain)
            return
        tt = {} if t is None else {"t": t}
        res = await self.d.set(path, data, meta, **tt)
        if not with_prev:
            return res[0]
        meta = MsgMeta.restore(res[1:]) if len(res) > 1 else None
        return res[0], meta

    @asynccontextmanager
    async def d_walk(
        self,
        path: Path,
        meta: bool = False,
        min_ts: float = 0,
        min_depth: int = 0,
        max_depth: int = 255,
    ) -> AsyncIterator[tuple[str, Any, MsgMeta]]:
        """
        Fetch a (limited) subtree.
        """
        args = [path, min_ts, min_depth, max_depth]
        if args[-1] == 255:
            args.pop()
            if args[-1] == 0:
                args.pop()
                if args[-1] == 0:
                    args.pop()

        async with self.d.walk(*args).stream_in() as mon:
            yield Walker(mon, meta=meta)

    # No use marking as Any|None if @mark is set
    @overload
    def d_watch(
        self,
        path: Path,
        mark: bool = False,
        meta: Literal[False] = False,
        subtree: Literal[False] = False,
        state: bool | Literal[NotGiven] | None = None,
    ) -> AbstractAsyncContextManager[AsyncIterator[Any]]: ...

    @overload
    def d_watch(
        self,
        path: Path,
        mark: Literal[False] = False,
        meta: Literal[True] = True,
        subtree: Literal[False] = False,
        state: bool | Literal[NotGiven] | None = None,
    ) -> AbstractAsyncContextManager[AsyncIterator[tuple[Any, MsgMeta]]]: ...

    @overload
    def d_watch(
        self,
        path: Path,
        mark: Literal[False],
        meta: Literal[True],
        subtree: Literal[True],
        state: bool | Literal[NotGiven] | None = None,
    ) -> AbstractAsyncContextManager[AsyncIterator[tuple[Path, Any, MsgMeta]]]: ...

    @overload
    def d_watch(
        self,
        path: Path,
        mark: Literal[False] = False,
        meta: Literal[False] = False,
        subtree: Literal[True] = True,
        state: bool | Literal[NotGiven] | None = None,
    ) -> AbstractAsyncContextManager[AsyncIterator[tuple[Path, Any]]]: ...

    @overload
    def d_watch(
        self,
        path: Path,
        mark: Literal[True],
        meta: Literal[True],
        subtree: Literal[False] = False,
        state: bool | Literal[NotGiven] | None = None,
    ) -> AbstractAsyncContextManager[AsyncIterator[None | tuple[Any, MsgMeta]]]: ...

    @overload
    def d_watch(
        self,
        path: Path,
        mark: Literal[True],
        meta: Literal[True],
        subtree: Literal[True],
        state: bool | Literal[NotGiven] | None = None,
    ) -> AbstractAsyncContextManager[AsyncIterator[None | tuple[Path, Any, MsgMeta]]]: ...

    @overload
    def d_watch(
        self,
        path: Path,
        mark: Literal[True],
        meta: Literal[False] = False,
        subtree: Literal[True] = True,
        state: bool | Literal[NotGiven] | None = None,
    ) -> AbstractAsyncContextManager[AsyncIterator[None | tuple[Path, Any]]]: ...

    def d_watch(
        self,
        path: Path,
        meta: bool = False,
        subtree: bool = False,
        state: bool | None | NotGiven = None,
        age: float | None = None,
        mark: bool = False,
        min_length: int | None = None,
        max_length: int | None = None,
        cls: type = Node,
    ) -> AbstractAsyncContextManager[AsyncIterator[tuple[Path, Any, MsgMeta]]]:
        """
        Monitor a node or subtree.

        @path: what to examine
        @meta: flag whether to return metadata too
        @subtree: flag whether to watch a subtree, not just this node
        @mark: yield `None` when the initial state has been transmitted
        @state: send the current state (True), updates (False), both with
                current data from the server (None), or both via MQTT (NotGiven).
        @age: cutoff this many seconds ago. Older entries are skipped.
        @cls: type of root node (default `Node`)

        This method returns an async context manager which yields an async iterator.
        The iterator yields node data if neither @subtree nor @meta is set.
        Otherwise it yields tuples. The first item is the path if @subtree
        is set; the last item is the metadata if @meta is set.

        ``state=NotGiven`` does not work with @mark=True, or when the same
        subscription is already active somewhere else.
        """
        return Watcher(self, path, meta, subtree, state, age, mark, cls, min_length, max_length)

    async def e_exc(self, path: Path, exc: Exception, **kw):
        """
        Report an exception, with backtrace.
        """
        exc = ungroup.one(exc)

        kw["_bt"] = format_exception(exc)
        kw["_exc"] = exc

        await self.e.exc(path, repr(exc), **kw)

    async def e_info(self, path: Path, txt: str, **kw):
        """
        Report a problem that's not an exception.
        """
        await self.e.info(path, txt, **kw)

    async def e_ack(self, path: Path, **kw):
        """
        Report that $USER has been notified of a problem.

        @ack can be True (don't notify any more), False (notify next
        time it happens), or a timestamp (notify if it happens again after
        $time).
        """
        await self.e.ack(path, **kw)

    async def e_ok(self, path: Path, **kw):
        """
        Report that something is working.
        """
        await self.e.ok(path, **kw)

    @asynccontextmanager
    async def e_wrap(self, path: Path, **kw):
        """
        An error-handling context manager. It opens a stream to the server
        and reports either success or failure over it.

        Streamed messages can be sent and will be stored as auxiliary
        information if the command should fail.

        This wrapper does *not* swallow the exception.
        """
        async with self.e.mon(path, **kw) as mon:
            yield mon
            await mon.send(True)

    def monitor(self, path: Path, *a, **kw) -> AbstractAsyncContextManager[AsyncIterator[Message]]:
        """
        Watch this path.

        This call forwards directly to the back-end.
        See `moat.link.backend.Backend.monitor` for call details.

        The caller is responsible for prefixing the Root path, if applicable.
        """
        return self._link.backend.monitor(path, *a, **kw)

    def send(self, path: Path, *a, **kw) -> Awaitable[None]:
        """
        Send to this path.

        This call forwards directly to the back-end.
        See `moat.link.backend.Backend.send` for call details

        The caller is responsible for prefixing the Root path, if applicable.
        """
        return self._link.backend.send(path, *a, **kw)

    async def i_sync(self):
        """
        This call tries to ensure that the server has processed all
        incoming MQTT messages.

        It does this by requesting a timestamp from the server, publishing
        the timestamp to MQTT, and then waiting for the server to
        acknowledge having received (at least) this number.

        This code assumes that MQTT messages are delivered in the order
        they are submitted. Depending on the server's multithreading setup
        this may or may not be true, but in practice it should be
        sufficiently true-ish to work out.

        It also assumes that if there's more than one server, they all have
        mostly-accurate time.
        """
        (st,) = await self.cmd(P("i.stamp"))
        await self.send(P(":R.run.service.main.stamp") / self._link.server_name, st, retain=False)
        await self.cmd(P("i.sync"), st)

    async def i_checkid(self, id: str) -> bool:
        """
        Check whether the given client ID is still valid.
        """
        (st,) = await self.cmd(P("i.checkid"), id)
        return st

    async def _get_tree(self, path, *, task_status, **kw):
        async with self.d_watch(path, **kw) as w:
            task_status.started(await w.get_node())
            await anyio.sleep_forever()

    async def get_codec_tree(self):
        """
        Returns a common subtree for codecs.
        """

        if self._codec_tree is None:
            self._codec_tree = evt = anyio.Event()

            from moat.link.node.codec import CodecNode  # noqa: PLC0415

            self._codec_tree = await self._link.tg.start(
                partial(
                    self._get_tree, P("codec"), subtree=True, state=None, meta=False, cls=CodecNode
                )
            )
            evt.set()

        elif isinstance(self._codec_tree, anyio.abc.Event):
            await self._codec_tree.wait()

        return self._codec_tree

    async def get_service(self, srv: Path) -> MsgHandler:
        res = await self.d_get(P("run.host") + srv)
        return self.sub_at(P("cl") / res["id"] + res["path"])


class Link(LinkCommon, CtxObj):
    """
    This class combines the back-end link with a connection to a MoaT-Link server.

    If "common" is set, create global state.
    """

    _server: ValueEvent = None
    _uptodate: bool = False
    _hello: Hello = None
    current_server: MsgSender = None
    _server_up: anyio.Event
    _last_link: Msg | None = None
    _last_link_seen: anyio.Event
    _port: str | None = None
    _state: str = "init"
    _common: bool = False
    announced: set[Path]

    def __new__(cls, cfg, name: str | None = None, common: bool = False):  # noqa:D102
        cfg, name  # noqa:B018
        if common and (link := _the_link.get(NotGiven)) is not NotGiven:
            return link
        return super().__new__(cls)

    def __init__(self, cfg, name: str | None = None, common: bool = False):
        if _the_link.get(NotGiven) is self:
            return
        super().__init__(cfg, name=name)
        self._retry_msgs: set[BasicCmd] = set()
        self._server_up = anyio.Event()
        self._state_change = anyio.Event()
        self._common = common
        self.announced = set()
        with suppress(AttributeError):
            self._port = self.cfg.client.port

    async def set_state(self, state: str):
        """
        Set the state string for our ping message
        """
        if state != self._state:
            self._state = state
            self._state_change.set()

    async def get_link(self):
        """
        This method refreshes the link to the server if it happens to be down.
        """
        while self.current_server is None:
            await self._server_up.wait()
        return self.current_server

    @property
    def _ping_path(self):
        return P("run.ping.id") / self._id

    @property
    def _id_path(self):
        return P("run.id") / self._id

    async def _send_id(self):
        await self.sdr.d_set(
            self._id_path,
            data=dict(
                host=platform.node(),
                pid=os.getpid(),
                argv=sys.argv,
            ),
            retain=True,
        )

    async def _send_ping(self, *, task_status=anyio.TASK_STATUS_IGNORED):
        """
        Periodially (or when our state changes) send a Ping.

        This also sends our ID message, after the first ping,
        but only if the task status isn't ignored.
        """
        path = Root.get() + self._ping_path
        while True:
            await self.backend.send(
                path,
                data=dict(
                    up=True,
                    state=self._state,
                ),
                retain=False,
                meta=False,
            )

            if task_status is not anyio.TASK_STATUS_IGNORED:
                # send initial run.id message, *after* the ping
                await self._send_id()
                task_status.started()
                task_status = anyio.TASK_STATUS_IGNORED

            if self._state == "init":
                self._state = "auto"

            with anyio.move_on_after(self.cfg.timeout.ping.every):
                await self._state_change.wait()
                self._state_change = anyio.Event()

    async def _monitor_ping(self, *, task_status=anyio.TASK_STATUS_IGNORED):
        path = Root.get() + self._ping_path
        async with self.backend.monitor(path) as mon:
            task_status.started()
            async for msg in mon:
                if msg.data is NotGiven:
                    raise ClientCancelledError(msg.meta)
                # anything else shall be ignored

    @asynccontextmanager
    async def _ctx(self):
        from .backend import get_backend  # noqa: PLC0415

        will = attrdict(
            data=dict(up=False, state="will"),
            topic=P(":R") + self._ping_path,
            retain=False,
            qos=QoS.AT_LEAST_ONCE,
        )
        async with (
            ctx_as(Root, self.cfg["root"]),
            get_backend(self.cfg, name=self.name, will=will) as self.backend,
            anyio.create_task_group() as self.tg,
        ):
            if self._port is not None:
                sdr = await self.tg.start(self._connected_port)
            else:
                if self.cfg.client.init_timeout:
                    # connect to the main server
                    await self.tg.start(self._run_server_link)
                sdr = LinkSender(self)
            sdr.add_sub("cl")
            sdr.add_sub("d")
            sdr.add_sub("e")
            sdr.add_sub("i")
            try:
                self.sdr = sdr
                await self.tg.start(self._monitor_ping)
                await self.tg.start(self._send_ping)

                with ctx_as(_the_link, self) if self._common else nullcontext():
                    yield sdr
            finally:
                del self.sdr
            await self.backend.send(
                Root.get() + self._ping_path,
                data=dict(up=False, state="closed"),
                retain=False,
                meta=False,
            )
            self.tg.cancel_scope.cancel()

    def cancel(self):
        "Stop me"
        self.tg.cancel_scope.cancel()

    async def _run_server_link(self, *, task_status=anyio.TASK_STATUS_IGNORED):
        """
        This is the manager task for the server link channel.
        It starts a server connection (and tries to keep it alive).
        """
        task_status = TS(task_status)

        with anyio.fail_after(self.cfg.client.init_timeout):
            srv = await self.tg.start(self._read_server_link)

        tm = self.cfg.timeout.connect
        timeout = tm.initial
        while True:
            try:
                await self._connect_server(srv, task_status=task_status)
            except Exception as exc:
                await self.backend.send_error(
                    P("run.service.main.server") / srv.meta.origin,
                    data=srv,
                    exc=exc,
                )
            finally:
                self.current_server = None
                if self._server_up.is_set():
                    self._server_up = anyio.Event()

                # TODO test if tasks from the remote side already get cancelled
                # TODO and if not, do that

            # Back off to either a new server announcement or the exponential timeout
            try:
                with anyio.fail_after(timeout):
                    await self._last_link_seen.wait()
            except TimeoutError:
                # try the last-reported connection again
                timeout = min(timeout * tm.factor, tm.max)
            else:
                # immediately use the new data
                srv = self._last_link
                self._last_link_seen = anyio.Event()

    async def _read_server_link(self, *, task_status=anyio.TASK_STATUS_IGNORED):
        # Background process that monitors the server link channel

        self._last_link_seen = anyio.Event()
        async with self.backend.monitor(
            P(":R.run.service.main.conn"),
            retain_handling=RetainHandling.SEND_RETAINED,
        ) as mon:
            async for msg in mon:
                self._last_link = msg
                if task_status is None:
                    self._last_link_seen.set()
                else:
                    task_status.started(msg)
                    task_status = None

    async def _connect_run(self, rem, *, task_status=anyio.TASK_STATUS_IGNORED):
        # We're connected.
        self.current_server = rem
        self._server_up.set()

        async def run_(cmd):
            await cmd.run(rem)

        async with anyio.create_task_group() as tg:
            for msg in self._retry_msgs:
                tg.start_soon(run_, msg)
            task_status.started()
            async for msg in self._cmdq_r:
                tg.start_soon(run_, msg)

    async def cmd(self, *a, _idem=False, **kw):
        """
        Queue and run a simple command.

        If @_idem is False, the command will error out if the connection
        dies while it's running. Otherwise (the default) it may be repeated.
        """
        cmd_ = BasicCmd(a, kw)
        try:
            self._retry_msgs.add(cmd_)
            while True:
                while self.current_server is None:
                    await self._server_up.wait()

                try:
                    with ungroup:
                        await self._cmdq_w.send(cmd_)
                        return await cmd_.result
                except _Requeue:
                    if _idem:
                        raise EOFError from None

        finally:
            self._retry_msgs.discard(cmd_)

    async def _connect_server(
        self,
        srv: Message[Data[S.run.service.main.conn]],
        *,
        task_status=anyio.TASK_STATUS_IGNORED,
    ):
        task_status = TS(task_status)

        # Backend connection
        link = srv.data["link"]
        if isinstance(link, dict):
            link = (link,)

        local_ok = srv.data.get("node", "localhost")

        for remote in link:
            if local_ok:
                pass
            elif "host" not in remote:
                continue
            elif remote["host"] in local_addrs:
                continue
            try:
                async with timed_ctx(
                    self.cfg.client.init_timeout, self._connect_one(remote, srv.data)
                ) as rem:
                    await self._connect_run(rem, task_status=task_status)
            except OSError as exc:
                self.logger.warning("Link failed: %r (%r)", remote, exc)
            except Exception as exc:
                self.logger.warning("Link failed: %r", remote, exc_info=exc)


class BasicLink(LinkCommon, CtxObj):
    """
    Simple direct link to a MQTT server.
    """

    def __init__(self, cfg, name: str | None, data: dict, **kw):
        super().__init__(cfg, name=name, **kw)
        self.data = data

    @asynccontextmanager
    async def _ctx(self):
        link = self.data["link"]
        if isinstance(link, dict):
            link = (link,)

        err = None
        yielded = False
        for remote in link:
            try:
                async with self._connect_one(remote, self.data) as self._sender:
                    yielded = True
                    yield self._sender
                    return
            except Exception as exc:
                if yielded:
                    raise
                self.logger.warning(
                    "Link failed: %r",
                    remote,
                    exc_info=None if isinstance(exc, EnvironmentError) else exc,
                )
                if err is None:
                    err = exc
            else:
                if not yielded and err is None:
                    err = EOFError

        if not yielded:
            if err is None:
                raise ValueError(f"No links in {self.data!r}")
            raise err


@define(eq=False)
class Watcher(CtxObj):
    """
    Helper class for monitoring (and coalescint the data of) either-or-both
    * a MQTT subscription to a subtree of our MoaT-Link hierarchy
    * a MoaT-Link request to enumerate a subtree
    """

    link: Link = field()
    path: Path = field()
    meta: bool = field()
    subtree: bool = field()
    state: bool | None | NotGiven = field()
    age: float | None = field()
    mark: bool = field()
    node_cls: type = field()
    min_length: type = field()
    max_length: type = field()

    _qr = field(init=False, repr=False)
    _tg = field(init=False, repr=False)
    _node = field(init=False, default=None)

    _current_done: anyio.Event | None = field(init=False, default=None)

    def __attrs_post_init__(self):
        if self.mark and self.state is NotGiven:
            raise ValueError("MQTT doesn't send a mark. Sorry.")
        if self.age is not None:
            self.age = time.time() - self.age

    def _chk(self, p, m):
        if self.age and m.timestamp < self.age:
            return False
        if self.min_length is not None and len(p) < self.min_length:
            return False
        if self.max_length is not None and len(p) > self.max_length:
            return False
        return True

    async def _current(self, qw, *, task_status):
        "get the current state from the server"
        if self.subtree:
            pl = PathLongener(())
            args = [self.path, self.age, self.min_length, self.max_length]
            while args[-1] is None:
                args.pop()
            async with self.link.d.walk(*args) as mon:
                task_status.started()
                async for r in mon:
                    n, p, d, *m = r
                    p = pl.long(n, p)
                    m = MsgMeta.restore(m)
                    if self._chk(p, m):
                        await qw.send((p, d, m))
                if self.mark:
                    await qw.send(None)
        else:
            try:
                r = await self.link.d.get(self.path)
            except (KeyError, ValueError):
                task_status.started()
            else:
                task_status.started()
                p, d, m = Path(), r[0], MsgMeta.restore(r[1:])
                if self._chk(p, m):
                    await qw.send((p, d, m))
            if self.mark:
                await qw.send(None)

        await qw.aclose()
        self._current_done.set()

    async def _updates(self, qw, *, task_status):
        "get updates from MQTT"
        plen = len(self.path)  # ignores the root prefix
        async with self.link.monitor(
            Root.get() + self.path, subtree=self.subtree, retained=(self.state is NotGiven)
        ) as mon:
            task_status.started()
            async for msg in mon:
                p, d, m = Path.build(msg.topic[plen:]), msg.data, msg.meta
                if self._chk(p, m):
                    await qw.send((p, d, m))
        await qw.aclose()

    @asynccontextmanager
    async def _ctx(self):
        async with anyio.create_task_group() as tg:
            self._node = self.node_cls()
            self._current_done = anyio.Event()
            self._tg = tg
            qw, self._qr = anyio.create_memory_object_stream(10)
            if self.state is not True:
                await tg.start(self._updates, qw.clone())
            if self.state is True or self.state is None:
                await tg.start(self._current, qw.clone())
            else:
                self._current_done.set()
                if self.mark:
                    await qw.send(None)
            await qw.aclose()
            yield self
            tg.cancel_scope.cancel()
            self._node = None

    def __aiter__(self):
        return self

    async def get_node(self, background=True) -> Node:
        """
        Wait until fetching the static data is complete, then return the
        watched node.

        If @background is set (the default), start a background job that
        updates the node. In this case you cannot iterate the watcher any
        more.
        """
        if background:
            await self._tg.start(self._iter)
        await self._current_done.wait()
        return self._node

    async def _iter(self, *, task_status: anyio.abc.TaskStatus):
        task_status.started()
        qr, self._qr = self._qr, None

        while True:
            try:
                msg = await qr.receive()
            except anyio.EndOfStream:
                return
            p, d, m = msg
            self._node.set(p, d, m)

    async def __anext__(self):
        while True:
            try:
                msg = await self._qr.receive()
            except anyio.EndOfStream:
                raise StopAsyncIteration from None
            if msg is None:
                return None
            p, d, m = msg
            if self._node.set(p, d, m, force=self._current_done.is_set()):
                if self.meta:
                    return (p, d, m) if self.subtree else (d, m)
                else:
                    return (p, d) if self.subtree else d


class Walker:
    """
    A trimmed-down watcher that retrieves a possibly-partial subtree
    from our MoaT-Link server.

    This differs from `Watcher` by not tracking updates, nor keeping a node
    tree in memory.
    """

    def __init__(self, mon, meta=False):
        self.mon = mon
        self.pl = PathLongener()
        self.meta = meta

    def __aiter__(self):
        return self

    async def __anext__(self):
        msg = await anext(self.mon)
        n, p, d, *m = msg.args
        p = self.pl.long(n, p)
        if self.meta:
            m = MsgMeta.restore(m)
            return p, d, m
        else:
            return p, d
