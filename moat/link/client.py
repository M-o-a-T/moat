"""
The MoaT-Link client
"""

from __future__ import annotations

import anyio
import logging
import time
import sys
from contextlib import asynccontextmanager, suppress, nullcontext, aclosing
from traceback import format_exception

import outcome
from attrs import define,field

from mqttproto import RetainHandling
from moat.lib.cmd.base import MsgSender, Caller
from moat.util import CtxObj, P, Root, ValueEvent, timed_ctx, gen_ident, ungroup, NotGiven,Path, PathLongener
from moat.util.compat import CancelledError
from moat.util.random import al_unique

from .common import CmdCommon
from .conn import TCPConn, UnixConn
from .auth import AnonAuth, TokenAuth
from .hello import Hello
from .meta import MsgMeta
from .node import Node

from typing import TYPE_CHECKING,overload
if TYPE_CHECKING:
    from typing import Any

class _Requeue(Exception):
    pass


from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Awaitable
    from typing import AsyncContextManager,AsyncIterator

    from moat.lib.cmd.base import MsgHandler
    from moat.lib.cmd.msg import Msg

    from .schema import Data
    from .schema import SchemaName as S
    from .backend import Message


__all__ = ["Link", "LinkCommon", "BasicLink"]


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
    protocol_version:int = -1
    name:str
    server_name:str

    def __init__(self, cfg, name: str | None = None, is_server:bool = False):
        self.cfg = cfg
        if name is None:
            name = cfg.get("client_id")
        if name is None:
            name = "_" + gen_ident(10, alphabet=al_unique)
        self.name = name
        self.is_server = is_server

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

    async def _connected_port(self, *, task_status=anyio.TASK_STATUS_IGNORED):
        async with self._connect_one(self._port) as hdl:
            task_status.started(hdl)
            await anyio.sleep_forever()

    @asynccontextmanager
    async def _connect_one(self, remote:dict|str, data: dict|None=None) -> MsgHandler:
        auth_out = []
        if isinstance(remote,dict):
            with suppress(KeyError):
                auth_out.append(TokenAuth(data["auth"]["token"]))
            conn_ = TCPConn(self, remote_host=remote["host"], remote_port=remote["port"])
        else:
            conn_ = UnixConn(self, path=remote, logger=self.logger.debug)

        auth_out.append(AnonAuth())
        self._hello = Hello(me=self.name, me_server=self.is_server, auth_out=auth_out)
        yielded = False


        async with conn_ as conn:
            handler = MsgSender(conn)
            if (res := await self._hello.run(handler)) is False:
                raise AuthError("Initial handshake failed")

            if isinstance(res,dict):
                name = res.pop("name",None)
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


class ClientCaller(Caller):
    def __init__(self,sender,*a,**kw):
        self._link = sender._link
        super().__init__(sender,*a,**kw)

    @asynccontextmanager
    async def _ctx(self):
        await self._link.get_link()
        async with super()._ctx() as res:
            yield res

    async def _call(self):
        "helper for __await__ that calls the remote handler"
        link = await self._link.get_link()
        cmd, a, kw = self.data
        return await link.root._sender.cmd(cmd, *a, **kw)


class _Sender(MsgSender):
    """
    This is the client-side front-end to a "standard" MoaT-Link connection.

    It contains various somewhat-high-level helpers. Most are named like
    the corresponding backend commands, with an underscore replacing the
    dot.
    """
    Caller_ = ClientCaller

    def __init__(self, link:LinkCommon):
        self._link = link
        self._allowed = set()

    def enable_path(self, path:Path):
        """
        This call protects against forgetting to prefix the root path, or
        similar bugs, when calling to the back-end directly.
        """
        self._allowed.add(path)

    @property
    def root(self):
        return self

    async def handle(self, msg: Msg, rcmd: list) -> Awaitable[None]:
        """
        Standard handler, forwards to the remote side.
        """
        srv = await self._link.get_link()
        await srv.handle(msg, rcmd)

    def find_handler(self, path, may_stream: bool = False) -> tuple[MsgHandler, Path]:
        """
        Standard sub-dispatcher redirector, no-op.
        """
        return self, path

    @overload
    def d_get(self, path:Path, meta:Literal[True]) -> tuple[Any,MsgMeta]:
        ...

    @overload
    def d_get(self, path:Path) -> Any:
        ...

    async def d_get(self, path:Path, meta:bool=False) -> tuple[Any,MsgMeta]:
        """
        Data retrieval. Calls the server's ``d.get`` method.

        Returns a data+metadata tuple if @meta is True, otherwise just the
        data.
        """
        if len(path) and isinstance(path[0],Path):
            raise ValueError("Don't use a root-prefixed path here.")

        res = await self.d.get(path)
        if not meta:
            return res[0]
        return res[0],MsgMeta.restore(res[1:])

    @overload
    def d_set(self, path:Path, t:float|None=None, meta:Literal[True]=True) -> tuple[Any,MsgMeta]:
        ...

    @overload
    def d_set(self, path:Path, t:float|None=None) -> None:
        ...

    async def d_set(self, path:Path, data:Any=NotGiven,
                    meta:MsgMeta|None=None, t:float|None=None,
                    with_prev:bool=False) -> None|tuple[Any,MsgMeta]:
        """
        Data update.

        If a timestamp is passed in @t or the old value+metadata is
        requested via @with_prev, goes through the server. Otherwise posts to
        MQTT directly.
        """
        if path and isinstance(path[0],Path):
            raise ValueError("Don't use a root-prefixed path here.")

        if meta is None:
            meta=MsgMeta(origin=self._link.name)
        if t is None and not with_prev:
            await self.send(Root.get()+path, data=data, meta=meta)
            return
        tt = {} if t is None else {"t":t}
        res = await self.d.set(path, data, meta, **tt)
        if not with_prev:
            return res[0]
        meta = MsgMeta.restore(res[1:]) if len(res)>1 else None
        return res[0],meta

    
    def d_watch(self, path:Path, meta:bool=False, subtree:bool=False, state:bool|None=None, max_age:float|None=None) -> AsyncContextManager[AsyncIterator[tuple]]:
        """
        Monitor a node or subtree.
        """
        return Watcher(self, path, meta, subtree, state, max_age)


    async def e_exc(self, path:Path, exc:Exception, **kw):
        """
        Report an exception, with backtrace.
        """
        exc = ungroup.one(exc)

        kw["_bt"]=format_exception(exc)
        kw["_exc"]=exc

        await self.e.exc(path,repr(exc),**kw)


    async def e_info(self, path:Path, txt:str, **kw):
        """
        Report a problem that's not an exception.
        """
        await self.e.info(path,txt,**kw)


    async def e_ack(self, path:Path, **kw):
        """
        Report that $USER has been notified of a problem.

        @ack can be True (don't notify any more), False (notify next
        time it happens), or a timestamp (notify if it happens again after
        $time).
        """
        await self.e.ack(path,**kw)


    async def e_ok(self, path:Path, **kw):
        """
        Report that something is working.
        """
        await self.e.ok(path,**kw)

    @asynccontextmanager
    async def e_wrap(self, path:Path, **kw):
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


    def monitor(self, path:Path, *a, **kw) -> AsyncContextManager[AsyncIterator[Message]]:
        """
        Watch this path.

        This call forwards directly to the back-end.
        See `moat.link.backend.Backend.monitor` for call details.

        The caller is responsible for prefixing the Root path, if applicable.
        """
        self._pcheck(path)
        return self._link.backend.monitor(path, *a, **kw)

    def send(self, path:Path, *a, **kw) -> Awaitable[None]:
        """
        Send to this path.

        This call forwards directly to the back-end.
        See `moat.link.backend.Backend.send` for call details

        The caller is responsible for prefixing the Root path, if applicable.
        """
        self._pcheck(path)
        return self._link.backend.send(path, *a, **kw)

    def _pcheck(self,path:Path):
        if not path:
            raise ValueError("Empty path?")
        if isinstance(path[0],Path):
            if path[0] == Root.get():
                return
            if path[0] in self._allowed:
                return
            raise ValueError("Prefix not allowed",path[0])
        root = Root.get()
        if path[:len(root)] == root:
            return
        for p in self._allowed:
            if path[:len(p)] == p:
                return
        raise ValueError("Path not allowed",path)


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
        await self.send(P(":R.run.service.main.stamp")/self._link.server_name, st)
        await self.cmd(P("i.sync"), st)


class Link(LinkCommon, CtxObj):
    """
    This class combines the back-end link with a connection to a MoaT-Link server.
    """

    _server: ValueEvent = None
    _uptodate: bool = False
    _hello: Hello = None
    current_server: MsgSender = None
    _server_up: anyio.Event
    _last_link: Msg | None = None
    _last_link_seen: anyio.Event
    _port: str|None=None

    def __init__(self, cfg, name: str | None = None):
        super().__init__(cfg, name=name)
        self._retry_msgs: set[BasicCmd] = set()
        self._server_up = anyio.Event()
        with suppress(AttributeError):
            self._port = self.cfg.client.port

    async def get_link(self):
        """
        This method refreshes the link to the server if it happens to be down.
        """
        while self.current_server is None:
            await self._server_up.wait()
        return self.current_server

    @asynccontextmanager
    async def _ctx(self):
        from .backend import get_backend

        async with (
            get_backend(self.cfg, name=self.name) as backend,
            anyio.create_task_group() as self.tg,
        ):
            self.backend = backend
            token = Root.set(self.cfg["root"])
            try:
                if self._port is not None:
                    sdr = await self.tg.start(self._connected_port)
                else:
                    if self.cfg.client.init_timeout:
                        # connect to the main server
                        await self.tg.start(self._run_server_link)
                    sdr = _Sender(self)
                sdr.add_sub("cl")
                sdr.add_sub("d")
                sdr.add_sub("e")
                sdr.add_sub("i")
                yield sdr
                self.tg.cancel_scope.cancel()
            finally:
                Root.reset(token)
            return

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

        for remote in link:
            try:
                async with timed_ctx(
                    self.cfg.client.init_timeout, self._connect_one(remote, srv.data)
                ) as rem:
                    await self._connect_run(rem, task_status=task_status)
            except Exception as exc:
                self.logger.warning("Link failed: %r", remote, exc_info=exc)


class BasicLink(LinkCommon, CtxObj):
    """
    Simple direct link to a server.
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
                self.logger.warning("Link failed: %r", remote, exc_info=exc)
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
    Helper class for monitoring.
    """
    link:Link=field()
    path:Path=field()
    meta:bool=field()
    subtree:bool=field()
    state:bool|None=field()
    age:float|None=field()

    _qw=field(init=False,repr=False)
    _qr=field(init=False,repr=False)
    _tg=field(init=False,repr=False)
    _node=field(init=False,default=None)

    _current_done:anyio.Event|None=field(init=False,default=None)

    def __attrs_post_init__(self):
        self._qw,self._qr = anyio.create_memory_object_stream(99)

    async def _current(self, *, task_status):
        "get the current state from the server"
        if self.subtree:
            pl = PathLongener(())
            async with self.link.d.walk(self.path) as mon:
                task_status.started()
                async for r in mon:
                    n,p,d,*m = r
                    p = pl.long(n,p)
                    m = MsgMeta.restore(m)
                    await self._qw.send((p,d,m))
        else:
            try:
                r = await self.link.d.get(self.path)
            except (KeyError,ValueError):
                task_status.started()
                # but do not do anything else
            else:
                task_status.started()
                p,d,m = Path(), r[0], MsgMeta.restore(r[1:])
                await self._qw.send((p,d,m))

        self._current_done.set()

    async def _updates(self, *, task_status):
        "get updates from MQTT"
        plen = 1+len(self.path)
        async with self.link.monitor(Root.get()+self.path, subtree=self.subtree) as mon:
            task_status.started()
            async for msg in mon:
                p,d,m = Path.build(msg.topic[plen:]),msg.data,msg.meta
                await self._qw.send((p,d,m))

    @asynccontextmanager
    async def _ctx(self):
        async with anyio.create_task_group() as tg:
            self._node = Node()
            self._tg = tg
            self._qw,self._qr = anyio.create_memory_object_stream(10)
            if self.state is not True:
                await tg.start(self._updates)
            if self.state is not False:
                self._current_done = anyio.Event()
                await tg.start(self._current)
            yield self
            tg.cancel_scope.cancel()
            await self._qw.aclose()
            self._node=None

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


    async def _iter(self, *, task_status:anyio.abc.TaskStatus):
        task_status.started()
        qr,self._qr = self._qr,None

        while True:
            try:
                msg = await qr.receive()
            except anyio.EndOfStream:
                return
            p,d,m = msg
            if self.age is None or m.timestamp+self.age >= time.time():
                self._node.set(p,d,m)

    async def __anext__(self):
        while True:
            try:
                msg = await self._qr.receive()
            except anyio.EndOfStream:
                raise StopAsyncIteration
            p,d,m = msg
            if self.age is None or m.timestamp+self.age >= time.time():
                if self._node.set(p,d,m):
                    if self.meta:
                        return (p,d,m) if self.subtree else (d,m)
                    else:
                        return (p,d) if self.subtree else d
