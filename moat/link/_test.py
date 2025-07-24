from __future__ import annotations

import anyio
import time
import os
import sys
from contextlib import asynccontextmanager, nullcontext
from tempfile import TemporaryDirectory
from pathlib import Path as FSPath
from functools import partial

from moat.link.client import Link
from moat.link.server import Server
from moat.link.backend import get_backend
from moat.util import (  # pylint:disable=no-name-in-module
    CFG,  # noqa:F401
    ensure_cfg,
    CtxObj,
    attrdict,
    combine_dict,
    NotGiven,
    Path,P,
    Root,
    ValueEvent,
)

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, AsyncIterator,Self

ensure_cfg("moat.link")


otm = time.time

_seq = 0


# TODO launch a "real" broker instead


async def run_broker(cfg, *, task_status):
    """
    Runs a basic MQTT broker.

    The task status returns the port we're listening on.
    """
    #cfg  # noqa:B018  # pyright:ignore
    #broker = AsyncMQTTBroker(("127.0.0.1", 0))
    #await broker.serve(task_status=task_status)
    port=40000+(os.getpid()+123)%10000
    async with (
            anyio.NamedTemporaryFile(mode="w+") as tf,
            anyio.create_task_group() as tg,
            ):
        await tf.write(f"""\
allow_anonymous true
retained_messages_mode enabled_without_persistence
thread_count 1

listen {{
    protocol mqtt
    port { port }
    inet4_bind_address 127.0.0.1
}}
""")
        await tf.flush()

        tg.start_soon(partial(anyio.run_process,["flashmq","-c",tf.name],stderr=sys.stderr,stdout=sys.stdout))
        for _ in range(20):
            try:
                sock = await anyio.connect_tcp("127.0.0.1",port)
            except EnvironmentError:
                await anyio.sleep(0.1)
            else:
                await sock.aclose()
                break
        else:
            raise RuntimeError("Could not connect to FlashMQ")

        task_status.started(port)


class Scaffold(CtxObj):
    """
    Basic testcase runner for testing with an ephemeral MQTT server.
    """
    tempdir:str|None

    def __init__(self, cfg: attrdict, use_servers=True, tempdir: str | None = None):
        ensure_cfg("moat.link.server", cfg)
        self.cfg = cfg.link

        self.cfg.setdefault("backend", attrdict())
        self.cfg.backend.setdefault("driver", "mqtt")
        self.cfg.backend.setdefault("codec", "std-cbor")
        self.cfg.backend.setdefault("keep_alive", 9999)

        self.cfg.server.ping.cycle=.5
        self.cfg.server.ping.gap=.15
        self.cfg.server.ping.override=True
        self.cfg.server.timeout.startup=3

        self._tempdir = tempdir

        if not use_servers:
            self.cfg.client.init_timeout = None

    @asynccontextmanager
    async def _ctx(self) -> AsyncIterator[Self]:
        Root.set(self.cfg.root)

        with (
            nullcontext(
                self._tempdir,
            )
            if self._tempdir is not None
            else TemporaryDirectory() as tempdir
        ):
            self.tempdir = FSPath(tempdir)
            async with anyio.create_task_group() as self.tg:
                bport = await self.tg.start(run_broker, self.cfg)

                self.cfg.backend.port = bport
                yield self
                self.tg.cancel_scope.cancel()  # pyright:ignore

    async def backend(self, cfg: dict | None = None, **kw):
        """
        Start a backend (background task)
        """
        return await self.tg.start(self._run_backend, cfg, kw)

    @asynccontextmanager
    async def backend_(self, cfg: dict | None, **kw) -> Backend:
        """
        Start a backend (async context manager).
        """
        cfg = combine_dict(cfg, self.cfg, cls=attrdict) if cfg else self.cfg
        async with get_backend(cfg, **kw) as bk:
            yield bk

    async def _run_backend(self, cfg: dict | None, kw: dict, *, task_status) -> Backend:
        """
        Start a backend (Helper).
        """
        async with self.backend_(cfg, **kw) as bk:
            task_status.started(bk)
            await anyio.sleep_forever()
            assert False  # noqa:B011,PT015

    async def server(self, cfg: dict | None = None, **kw) -> tuple[Server, list[dict]]:
        """
        Start a server (background task)

        Returns the server object and the ports it runs on.
        """
        return await self.tg.start(self._run_server, cfg, kw)

    async def _run_server(self, cfg, kw, *, task_status) -> None:
        """
        Run a basic MoaT-Link server. (Helper task)
        """
        cfg = combine_dict(cfg, self.cfg, cls=attrdict) if cfg else self.cfg
        if "ports" in cfg["server"]:
            cfg["server"]["ports"]["main"]["port"] = 0
        cfg["server"]["port"] = 0
        if self.tempdir is not None:
            cfg["server"]["save"]["dir"] = self.tempdir / "data"
        global _seq  # noqa:PLW0603
        _seq += 1

        s = Server(cfg, f"S_{_seq}", **kw)
        await s.serve(task_status=task_status)

    @asynccontextmanager
    async def server_(self, cfg:dict|None=None, **kw) -> None:
        """
        Runs a basic MoaT-Link server. (async context manager)
        """
        async with anyio.create_task_group() as tg:
            yield await tg.start(self._run_server,cfg,kw)
            tg.cancel_scope.cancel()

    async def client(self, *a, **kw):
        """
        Start a client (background task)
        """
        cl = await self.tg.start(partial(self._run_client, *a, **kw))
        return cl

    async def _run_client(self, *a, task_status, **kw) -> Never:
        async with self.client_(*a, **kw) as li:
            task_status.started(li)
            await anyio.sleep_forever()
            assert False  # noqa:B011,PT015

    @asynccontextmanager
    async def client_(self, cfg:dict|None=None, cli:LinkCommon|None=None, name=None) -> Never:
        """
        Start a client (async context manager)
        """
        if cli is None:
            cfg = combine_dict(cfg, self.cfg, cls=attrdict) if cfg else self.cfg

            global _seq  # noqa:PLW0603
            _seq += 1
            name = f"C_{_seq}"

            cli = Link(cfg,name)

        async with cli as li:
            yield li

    @asynccontextmanager
    async def do_watch(self, path, exp=NotGiven, n=0, *a, **kw):
        """
        Run a client that expects @xp and appends all non-exp
        results to @rd.

        All other args+kw are forwarded to `Link.d_watch`.
        """
        async with anyio.create_task_group() as tg, self.client_() as c:
            evt = ValueEvent()
            got=0
            @tg.start_soon
            async def work():
                res=[]
                try:
                    async with c.d_watch(path,*a,**kw) as mon:
                        async for r in mon:
                            if not kw.get("meta") and not kw.get("subtree"):
                                r = (r,)
                            if kw.get("meta"):
                                t = time.time()
                                assert t - 1 < r[-1].timestamp < t
                            if exp is not NotGiven and (not kw.get("subtree") or not len(r[0])) and r[kw.get("subtree",0)] == exp:
                                return
                            res.append(r)
                            if len(res)==n:
                                return
                finally:
                    evt.set(res)
            yield evt
            tg.cancel_scope.cancel()



