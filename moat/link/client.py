from __future__ import annotations

from contextlib import asynccontextmanager, AsyncExitStack
import time
import anyio

from asyncscope import Scope, main_scope, scope

from moat.util import OptCtx, CtxObj, ValueEvent, Root
from moat.lib.cmd import CmdHandler


@asynccontextmanager
async def open_link(cfg, _main_name="moat.link", name:str=None):
    """
    This async context manager returns an opened MoaT link.
    """

    async with OptCtx(main_scope(name=_main_name) if scope.get() is None else None):
        yield await link_scope(cfg, name=name)


async def _scoped_link(cfg, __name:str|None=None):
    """
    AsyncScope service for a link bundle.
    """
    link = Link(cfg,name=__name)
    async with link:
        scope.register(link)
        await scope.wait_no_users()


async def link_scope(cfg, name:str|None = None):
    """
    Returns a link, by way of an asyncscope service.
    """

    _name = cfg.get("name", "std")
    return await scope.service(
        f"moat.link.{_name}", _scoped_link, cfg=cfg, __name=name
    )


class Link(CtxObj):
    """
    This class collects and dispatches a number of MoaT links.

    See `Link` for calling conventions.
    """
    _server:ValueEvent = None
    _current_server:dict = None
    _uptodate:bool = False

    def __init__(self, cfg, name:str|None=None):
        self.cfg = cfg
        self.name = name
        self._cmd = CmdHandler(self._cmd_other_cb)

    async def _cmd_other_cb(self, msg):
        """Callback for command-channel messages from the server"""
        logger.warning("Unknown message: %r", msg)
        # TODO add client-side commands like get-state or graceful-shutdown

    async def _mon_server(self, *, task_status):
        async with self.mqtt.subscription(self.cfg.root) as sub:
            self._server = ValueEvent()
            task_status.started(self._server)

            async for msg in sub:
                self._current_server = msg.msg
                self._server.set(msg.msg)
                self._server = ValueEvent()

    async def _run_cmd_server(self):
        from moat.lib.anyio import run
        async with await anyio.connect_tcp(server["host"], server["port"]) as conn:
            await run(self._cmd, conn)


    def do_cmd(self, *a, **kw) -> Awaitable:
        return self._cmd.cmd(*a, **kw)

    async def _cmd_server(self, server, *, task_status):
        server_updated = self._server
        retry = 1  # initially we delay for longer
        while True:

            try:
                await self._run_cmd_server(server)
            except EOFError as exc:
                logger.warning("Link to %s down", server, exc_info=exc)

            if self._uptodate:
                self._uptodate = False
                retry = 0.1
            else:
                with anyio.move_on_after(retry):
                    await server_updated.wait()
                    server_updated = self._server
                retry *= 1.2

            server = self._current_server


    @asynccontextmanager
    async def _ctx(self):
        from .backend import get_backend

        async with (
                get_backend(self.cfg, name=self.name) as backend,
                anyio.create_task_group() as tg,
                self._cmd,
        ):
            self.backend = backend
            try:
                token = Root.set(self.cfg["root"])
                yield self
            finally:
                Root.reset(token)
            return

    def monitor(self, *a, **kw):
        return self.backend.monitor(*a,**kw)

    def send(self, *a, **kw):
        return self.backend.send(*a,**kw)


async def _masked():
    if False:
        if False:

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
            self._scan.extend([None] * (i-len(self._scan) + 1))
            if (d := self._scan[i]) is None:
                self._scan[i] = d = {}
            d[path] = _LinkDummy(self, p)

        if self._scan[0] is None:
            self._scan[0] = {(): _LinkDead(self, "No such link")}

    async def _ctx(self):
        async with AsyncExitStack() as self._stack:
            yield self

    async def backend(self, path):
        i = min(len(path)+1, len(self._scan))
        while True:
            i -= 1
            d = self._scan[i]
            if d is None:
                continue
            d = d.get(path[:i])
            if d is not None:
                break

        if isinstance(d,_LinkDummy):
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

    async def set(self, path: Path, *a, **k) -> None:
        b = await self.backend(path)
        return await b.set(path, *a, **k)

    async def dir(self, path: Path, *a, **k) -> AsyncIterable[str|list]:
        b = await self.backend(path)
        return await b.dir(path, *a, **k)

    async def monitor(self, path: Path, *a, **k) -> AsyncIterable[Any]:
        b = await self.backend(path)
        return await b.monitor(path, *a, **k)

