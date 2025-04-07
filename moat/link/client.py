"""
The MoaT-Link client
"""

from __future__ import annotations

import anyio
import logging
from contextlib import asynccontextmanager, suppress, nullcontext

import outcome

try:
    from mqttproto import RetainHandling
except ImportError:
    from moat.lib.mqttproto import RetainHandling

from moat.lib.cmd.base import MsgSender, MsgHandler
from moat.util import CtxObj, P, Root, ValueEvent, timed_ctx, gen_ident
from moat.util.compat import CancelledError

from .common import CmdCommon
from .conn import TCPConn
from .auth import AnonAuth, TokenAuth
from .hello import Hello

class _Requeue(Exception):
    pass

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .schema import Data
    from .schema import SchemaName as S
    from .backend import Message
    from moat.lib.cmd.base import MsgHandler

    from collections.abc import Awaitable

__all__ = ["Link","LinkCommon","BasicLink"]


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

    def __init__(self, a, kw, idem):
        self.a = a
        self.kw = kw
        self.idem = idem
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
        except BaseException:
            raise
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


class LinkCommon(CmdCommon, MsgHandler, CtxObj):
    def __init__(self, cfg, name: str | None = None):
        self.cfg = cfg
        self.name = name
        if name is None:
            name = cfg.get("client_id")
        if name is None:
            name = "c_" + gen_ident(10, alphabet_al_unique)

        self._cmdq_w, self._cmdq_r = anyio.create_memory_object_stream(5)
        self.logger = logging.getLogger(f"moat.link.client.{name}")

    async def _ctx(self):
        raise RuntimeError("don't use this as a context manager")

    def handle(self, msg, rpath, *add) -> Awaitable[Any]:
        """
        Message handlers that intercepts commands, as long as no
        authorization has taken place
        """
        if self._hello is not None and self._hello.auth_data is None:
            return self._hello.handle(msg, rpath, *add)

        return super().handle(msg, rpath, *add)

    def sub_at(self, prefix: Path, may_stream: bool = False) -> tuple[MsgHandler, Path]:
        """
        Prevent subpath lookup while auth is incomplete
        """
        if self._hello.auth_data is None:
            return self, path
        return super().sub_at(prefix, may_stream=may_stream)

    @asynccontextmanager
    async def _connect_one(self, remote, data: dict) -> MsgHandler:
        auth_out = []
        with suppress(KeyError):
            auth_out.append(TokenAuth(data["auth"]["token"]))
        auth_out.append(AnonAuth())
        self._hello = Hello(me=self.name, auth_out=auth_out)

        async with TCPConn(self, remote_host=remote["host"], remote_port=remote["port"]) as conn:
            handler = MsgSender(conn)
            self.logger.warning("HelloCliStart")
            if await self._hello.run(handler) is False:
                raise AuthError("Initial handshake failed")
            self.logger.warning("HelloCliDone")
            yield handler
            self.logger.warning("CliDone1")
        self.logger.warning("CliDone2")


class _Sender(MsgSender):
    def __init__(self, link):
        self._link = link

    @property
    def root(self):
        return self._link.current_server

    async def handle(self, msg: Msg, rcmd: list) -> Awaitable[None]:
        srv = await self._link.get_link()
        await srv.handle(msg, rcmd)


    def monitor(self, *a, **kw):
        "watch this path; see backend doc"
        return self._link.backend.monitor(*a, **kw)

    def send(self, *a, **kw):
        "send to this path; see backend doc"
        return self._link.backend.send(*a, **kw)

    async def sync(self):
        "sync with our server"
        st, = await self.cmd(P("i.stamp"))
        await self.send(P(":R.run.service.main.stamp"), st)
        await self.cmd(P("i.sync"),st)
    
    def stream(self, *a, **kw):
        return self.cmd(*a,**kw).stream()
    
    def stream_in(self, *a, **kw):
        return self.cmd(*a,**kw).stream_in()
    
    def stream_out(self, *a, **kw):
        return self.cmd(*a,**kw).stream_out()

class Link(LinkCommon):
    """
    This class combines the back-end link with a connection to a MoaT-Link server.
    """

    _server: ValueEvent = None
    _uptodate: bool = False
    _hello: Hello = None
    current_server:MsgSender = None
    _server_up:anyio.Event

    def __init__(self, cfg, name: str | None = None):
        super().__init__(cfg, name=name)
        self._retry_msgs: set[BasicCmd] = set()
        self._server_up = anyio.Event()

    async def get_link(self):
        while self.current_server is None:
            await self._server_up.wait()
        return self.current_server

    async def _mon_server(self, *, task_status):
        async with self.mqtt.subscription(self.cfg.root) as sub:
            self._server = ValueEvent()
            task_status.started(self._server)

            async for msg in sub:
                self._server.set(msg.msg)
                self._server = ValueEvent()

        return self._handler.stream_r(*a, **kw)

    @asynccontextmanager
    async def _ctx(self):
        from .backend import get_backend

        async with (
            get_backend(self.cfg, name=self.name) as backend,
            anyio.create_task_group() as self.tg,
        ):
            self.backend = backend
            try:
                token = Root.set(self.cfg["root"])
                if self.cfg.client.init_timeout:
                    # connect to the main server
                    await self.tg.start(self._run_server_link)
                yield _Sender(self)
            finally:
                Root.reset(token)
            return

    def cancel(self):
        "Stop me"
        self.tg.cancel_scope.cancel()

    async def _run_server_link(self, *, task_status=anyio.TASK_STATUS_IGNORED):
        # Manager for the server link channel. Repeats running a server
        # connection.
        task_status = TS(task_status)

        with anyio.fail_after(self.cfg.client.init_timeout):
            srv = await self.tg.start(self._read_server_link)

        tm = self.cfg.timeout.connect
        timeout = tm.initial
        while True:
            try:
                await self._connect_server(srv, task_status=task_status)
            except Exception as exc:
                raise  # XXX
                await self.backend.send_error(
                    P("run.service.main") / srv.meta.origin / self.name,
                    data=srv,
                    exc=exc,
                )
            finally:
                self.current_server = None
                if self._server_up.is_set():
                    self._server_up = anyio.Event()

            # TODO save (some) currently-running commands for re-execution
            # TODO cancel tasks from the remote side
            try:
                with anyio.fail_after(timeout):
                    await self._last_link_seen.wait()
            except TimeoutError:
                # try the last-tried connection again
                timeout = min(timeout * tm.factor, tm.max)
            else:
                # immediately use the new data
                srv = self._last_link
                self._last_link_seen = anyio.Event()

    async def _read_server_link(self, *, task_status=anyio.TASK_STATUS_IGNORED):
        # Background process that monitors the server link channel

        self._last_link_seen = anyio.Event()
        async with self.backend.monitor(
            P(":R.run.service.main"),
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

    async def cmd(self, *a, _idem=True, **kw):
        """
        Queue and run a simple command.

        If @_idem is False, the command will error out if the connection
        ends while it's running. Otherwise (the default) it may be repeated.
        """
        if not _idem:
            while self.current_server is None:
                await self._server_up.wait()
            return await self.current_server.cmd(*a, **kw)

        cmd = BasicCmd(a, kw, _idem)
        try:
            while True:
                await self._cmdq_w.send(cmd)
                try:
                    return await cmd.result
                except _Requeue:
                    raise

        finally:
            self._retry_msgs.discard(cmd)


    async def _connect_server(
        self,
        srv: Message[Data[S.run.service.main]],
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
                    self.cfg.client.init_timeout,
                    self._connect_one(remote, srv.data)
                ) as rem:
                    await self._connect_run(rem, task_status=task_status)
            except Exception as exc:
                self.logger.warning("Link failed: %r", remote, exc_info=exc)


class BasicLink(LinkCommon):
    """
    Simple direct link to a server.
    """

    def __init__(self, cfg, name: str | None, data: dict):
        super().__init__(cfg, name=name)
        self.data = data

    async def _ctx(self):
        link = self.data["link"]
        if isinstance(link, dict):
            link = (link,)

        err = None
        yielded = False
        for remote in link:
            try:
                async with self._connect_one(remote, self.data) as self._handler:
                    yielded = True
                    yield self
                    return
            except Exception as exc:
                if yielded:
                    raise
                self.logger.warning("Link failed: %r", remote, exc_info=exc)
                if err is None:
                    err = exc
        else:
            raise ValueError(f"No links in {self.data !r}")
        raise err
