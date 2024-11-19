"""
The MoaT-Link client
"""

from __future__ import annotations

import anyio
import logging
from contextlib import AsyncExitStack, asynccontextmanager

import outcome
from mqttproto import RetainHandling

from moat.lib.cmd import CmdHandler
from moat.lib.cmd.anyio import run as run_stream
from moat.util import CtxObj, P, Path, Root, ValueEvent, import_

from . import protocol_version

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .schema import Data
    from .schema import SchemaName as S

    from typing import Any, AsyncIterable, Awaitable

__all__ = ["Link"]


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
    A simple command that doesn't require restarts or streaming.
    """

    def __init__(self, a, kw):
        self.a = a
        self.kw = kw
        self._result = None
        self._evt = anyio.Event()

    def run(self, link):
        "run the command"
        try:
            res = link.cmd(*self.a, **self.kw)
        except anyio.get_cancelled_exc_class():
            raise
        except Exception as exc:
            self._result = outcome.Error(exc)
        else:
            self._result = outcome.Value(res)
        self._evt.set()

    @property
    async def result(self):
        "retreve the result"
        await self._evt.wait()
        return self._result.unwrap()


class Link(CtxObj):
    """
    This class collects and dispatches a number of MoaT links.

    See `Link` for calling conventions.
    """

    _server: ValueEvent = None
    _current_server: dict = None
    _uptodate: bool = False

    def __init__(self, cfg, name: str | None = None):
        self.cfg = cfg
        self.name = name
        self._cmd = CmdHandler(self._cmd_other_cb)
        self._cmdq_w, self._cmdq_r = anyio.create_memory_object_stream(5)
        self._retry_msgs: set[BasicCmd] = set()
        self._login_done:anyio.Event=anyio.Event()

        if name is None:
            name = cfg.get("client_id")
        if name is None:
            import random

            name = "c_" + "".join(
                random.choices("bcdfghjkmnopqrstvwxyzBCDFGHJKMNOPQRSTVWXYZ23456789", k=10)
            )
        self.logger = logging.getLogger(f"moat.link.client.{name}")

    async def _cmd_other_cb(self, msg):
        """Callback for command-channel messages from the server"""
        self.logger.warning("Unknown message: %r", msg)
        raise RuntimeError("No such command")
        # TODO add client-side commands like get-state or graceful-shutdown

    async def _mon_server(self, *, task_status):
        async with self.mqtt.subscription(self.cfg.root) as sub:
            self._server = ValueEvent()
            task_status.started(self._server)

            async for msg in sub:
                self._current_server = msg.msg
                self._server.set(msg.msg)
                self._server = ValueEvent()

    def stream_r(self, *a, **kw) -> Awaitable:
        """
        Complex command, reading
        """
        return self._cmd.stream_r(*a, **kw)

    def stream_w(self, *a, **kw) -> Awaitable:
        """
        Complex command, writing
        """
        return self._cmd.stream_w(*a, **kw)

    def stream_rw(self, *a, **kw) -> Awaitable:
        """
        Complex command, bidirectional
        """
        return self._cmd.stream_rw(*a, **kw)

    @asynccontextmanager
    async def _ctx(self):
        from .backend import get_backend

        async with (
            get_backend(self.cfg, name=self.name) as backend,
            anyio.create_task_group() as self.tg,
            self._cmd,
        ):
            self.backend = backend
            try:
                token = Root.set(self.cfg["root"])
                if self.cfg.client.init_timeout:
                    # monitor main server
                    await self.tg.start(self._run_server_link)

                await self._login_done.wait()
                yield self
            finally:
                Root.reset(token)
            return

    def cancel(self):
        "Stop me"
        self.tg.cancel_scope.cancel()

    async def _process_server_cmd(self, msg):
        #cmd = msg.cmd if isinstance(msg.cmd, (Sequence,Path)) else (msg.cmd,)
        #cmd = "_".join(str(x) for x in cmd)
        #fn = getattr(self, "cmd_" + str(cmd), None)
        if msg.cmd == P("i.hello"):
            return True
        raise RuntimeError(f"I don't know how to process cmd {msg.cmd}")

    async def _run_server_link(self, *, task_status=anyio.TASK_STATUS_IGNORED):
        # Manager for the server link channel. Repeats running a server
        # connection.
        task_status = TS(task_status)

        with anyio.fail_after(self.cfg.client.init_timeout):
            srv = await self.tg.start(self._read_server_link)

        self._cmd_link = CmdHandler(self._process_server_cmd)

        while True:
            try:
                await self._connect_server(srv, task_status=task_status)
            except Exception as exc:
                raise  # XXX
                await self.backend.send_error(
                    P("run.service.main") / srv.meta.origin / self.name, data=srv, exc=exc
                )
            finally:
                self._server_up = False

            # TODO save (some) currently-running commands for re-execution
            # TODO cancel tasks from the remote side
            try:
                with anyio.fail_after(5):  # todo: back-off
                    await self._last_link_seen.wait()
            except TimeoutError:
                # try the last-tried connection again
                pass
            else:
                # immediately use the new data
                srv = self._last_link_seen
                self._last_link_seen = anyio.Event()

    async def _read_server_link(self, *, task_status=anyio.TASK_STATUS_IGNORED):
        # Background process that monitors the server link channel

        self._last_link_seen = anyio.Event()
        async with self.backend.monitor(
            P(":R.run.service.main"), retain_handling=RetainHandling.SEND_RETAINED
        ) as mon:
            async for msg in mon:
                if task_status is None:
                    self._last_link = msg
                    self._last_link_seen.set()
                else:
                    task_status.started(msg)
                    task_status = None

    async def _connect_run(self, *, task_status=anyio.TASK_STATUS_IGNORED):
        # We're connected.
        self._server_up = True

        async def run_(cmd):
            await cmd.run(self._cmd)

        async with anyio.create_task_group() as tg:
            for msg in self._retry_msgs:
                tg.start_soon(run_, msg)
            task_status.started()
            async for msg in self._cmdq_r:
                tg.start_soon(run_, msg)

    async def cmd(self, *a, **kw):
        "Queue and run a simple command"
        cmd = BasicCmd(a, kw)
        await self._cmdq_w.send(cmd)
        try:
            self._retry_msgs.add(cmd)
            return await cmd.result
        finally:
            self._retry_msgs.discard(cmd)

    async def _connect_server(self, srv: Message[Data[S.run.service.main]], *, task_status=anyio.TASK_STATUS_IGNORED):
        task_status = TS(task_status)

        # Backend connection
        link = srv.data["link"]
        if isinstance(link, dict):
            link = (link,)

        for remote in link:
            try:
                async with self._connect_one(remote, srv):
                    await self._connect_run(task_status=task_status)
            except Exception as exc:
                self.logger.warning("Link failed: %r", remote, exc_info=exc)

    @asynccontextmanager
    async def _connect_one(self, remote, srv:Message):
        cmd = self._cmd_link
        async with (
            await anyio.connect_tcp(remote["host"], remote["port"]) as stream,
            run_stream(cmd, stream),
        ):
            await self._send_hello(srv)
            yield self

    async def _send_hello(self,srv):
        "Send hello message, do authorization if required"

        cmd = self._cmd_link
        res = await cmd.cmd(P("i.hello"), protocol_version, self.name, srv.meta.origin, srv.data.get("auth", True))
        it = iter(res)
        self.link_protocol = protocol_version
        self._server_name = srv.meta.origin
        auth = True

        try:
            prot = next(it)
            if prot is False:
                raise ValueError("Protocol mismatch")
            elif prot is None:
                pass
            else:
                self.link_protocol = min(tuple(prot), protocol_version)

            server_name = next(it)
            if server_name is None:
                pass
            elif server_name != srv.meta.origin:
                self.logger.warning("Server name: %r / %r", server_name, srv.meta.origin)

            name = next(it)
            if name is not None:
                if self.name:
                    self.logger.warning("Client name: %r / %r", name, self.name)
                self.name = name

            if not next(it):
                raise RuntimeError("Not talking to a server")

            auth = next(it)
        except StopIteration:
            pass

        if auth is True:
            self._login_done.set()
        elif auth is False:
            raise RuntimeError("Server %r didn't like us", srv.meta.origin)
        elif isinstance(auth, str):
            if not await self._do_auth(auth):
                raise RuntimeError("No auth with %s", auth)
        else:
            for m in auth:
                if await self._do_auth(m):
                    break
            else:
                raise RuntimeError("No auth with %s", auth)

    def monitor(self, *a, **kw):
        "watch this path; see backend doc"
        return self.backend.monitor(*a, **kw)

    def send(self, *a, **kw):
        "send to this path; see backend doc"
        return self.backend.send(*a, **kw)


async def _masked():
    class _LinkDummy:
        pass

    class _LinkDead:
        pass

    async def _cmd_server(self, server, *, task_status):
        server_updated = self._server
        task_status = TS(task_status)

        retry = 1  # initially we delay for longer
        while True:
            try:
                await self._run_cmd_server(server, task_status=task_status)
            except EOFError as exc:
                self.logger.warning("Link to %s down", server, exc_info=exc)

            # reset backoff if successful
            if self._uptodate:
                self._uptodate = False
                retry = 0.1
            else:
                with anyio.move_on_after(retry):
                    await server_updated.wait()
                    server_updated = self._server
                retry *= 1.2

            server = self._current_server

    async def _run_cmd_server(self, server, *, task_status):
        async with (
            await anyio.connect_tcp(server["host"], server["port"]) as conn,
            run_stream(self._cmd, conn),
        ):
            task_status.started()
            raise RuntimeError("obsolete")

    async def foo(self):
        if tg := False:
            server = await tg.start(self._mon_server)
            with anyio.fail_after(self.cfg.client.init_timeout):
                server = await server.get()
            await tg.start(self._cmd_server, server)

        self._scan = []
        self._stack = None
        self._backends = {}

        for p in self.cfg["dist"]:
            path = p["path"]
            i = len(path)
            self._scan.extend([None] * (i - len(self._scan) + 1))
            if (d := self._scan[i]) is None:
                self._scan[i] = d = {}
            d[path] = _LinkDummy(self, p)

        if self._scan[0] is None:
            self._scan[0] = {(): _LinkDead(self, "No such link")}

    async def _ctx(self):
        async with AsyncExitStack() as self._stack:
            yield self

    async def backend(self, path):
        i = min(len(path) + 1, len(self._scan))
        while True:
            i -= 1
            d = self._scan[i]
            if d is None:
                continue
            d = d.get(path[:i])
            if d is not None:
                break

        if isinstance(d, _LinkDummy):
            if d.waiting is not None:
                await d.waiting
                d = self._scan[i][path[:i]]
            else:
                evt = d.waiting = anyio.Event()
                cls = import_("moat.link.backend.{d.cfg['']}")
                try:
                    d = await self._stack.enter_async_context(cls(d.name, d.cfg))
                except BaseException:
                    self._scan[i][path[:i]] = _LinkDead()
                    raise
                finally:
                    evt.set()
                self._scan[i][path[:i]] = d

        return d

    async def get(self, path: Path, *a, **k) -> Any:
        b = await self.backend(path)
        return await b.get(path, *a, **k)

    async def set(self, path: Path, *a, **k) -> None:  # noqa:A001
        b = await self.backend(path)
        return await b.set(path, *a, **k)

    async def dir(self, path: Path, *a, **k) -> AsyncIterable[str | list]:  # noqa:A001
        b = await self.backend(path)
        return await b.dir(path, *a, **k)

    async def monitor(self, path: Path, *a, **k) -> AsyncIterable[Any]:
        b = await self.backend(path)
        return await b.monitor(path, *a, **k)
