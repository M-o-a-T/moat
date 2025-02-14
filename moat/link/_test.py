from __future__ import annotations

import anyio
import logging
import time
from contextlib import asynccontextmanager, nullcontext
from tempfile import TemporaryDirectory
from pathlib import Path as FSPath

try:
    from mqttproto.async_broker import AsyncMQTTBroker
except ImportError:
    from moat.lib.mqttproto.async_broker import AsyncMQTTBroker

from moat.link.client import Link
from moat.link.server import Server
from moat.link.backend import get_backend
from moat.util import (  # pylint:disable=no-name-in-module
    CFG as CFG,
    ensure_cfg,
    CtxObj,
    attrdict,
    combine_dict,
    Root,
)

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Never

ensure_cfg("moat.link")


logger = logging.getLogger(__name__)

otm = time.time

_seq = 0


# TODO launch a "real" broker instead


async def run_broker(cfg, *, task_status):
    """
    Runs a basic MQTT broker.

    The task status returns the port we're listening on.
    """
    cfg  # noqa:B018
    broker = AsyncMQTTBroker(("127.0.0.1", 0))

    await broker.serve(task_status=task_status)


class Scaffold(CtxObj):
    tempdir=None

    def __init__(self, cfg: attrdict, use_servers=True, tempdir:str|None=None):
        self.cfg = cfg.link

        self.cfg.setdefault("backend", attrdict())
        self.cfg.backend.setdefault("driver", "mqtt")
        self.cfg.backend.setdefault("codec", "std-cbor")
        self._tempdir=tempdir

        if not use_servers:
            self.cfg.client.init_timeout = None

    @asynccontextmanager
    async def _ctx(self):
        Root.set(self.cfg.root)

        with nullcontext(self._tempdir) if self._tempdir is not None else TemporaryDirectory() as tempdir:
            self.tempdir=FSPath(tempdir)
            async with anyio.create_task_group() as self.tg:
                bport = await self.tg.start(run_broker, self.cfg)

                self.cfg.backend.port = bport
                yield self
                self.tg.cancel_scope.cancel()

    async def _run_backend(self, cfg: dict | None, kw: dict, *, task_status) -> Backend:
        """
        Start a backend.
        """
        cfg = combine_dict(cfg, self.cfg) if cfg else self.cfg
        async with get_backend(cfg, **kw) as bk:
            task_status.started(bk)
            await anyio.sleep_forever()
            assert False  # noqa:B011,PT015

    async def server(self, cfg: dict | None = None, **kw) -> tuple[Server,list[dict]]:
        """
        Start a server.
        Returns the server object and the ports it runs on.
        """
        cfg = combine_dict(cfg, self.cfg) if cfg else self.cfg
        cfg["server"]["ports"]["main"]["port"] = 0
        cfg["server"]["save"]["dir"] = self.tempdir/"data"
        return await self.tg.start(self._run_server, cfg, kw)

    async def client(self, cfg: dict | None = None):
        cfg = combine_dict(cfg, self.cfg) if cfg else self.cfg
        return await self.tg.start(self._run_client, cfg)

    async def backend(self, cfg: dict | None = None, **kw):
        cfg = combine_dict(cfg, self.cfg) if cfg else self.cfg
        return await self.tg.start(self._run_backend, cfg, kw)

    async def _run_server(self, cfg, kw, *, task_status) -> Never:
        """
        Runs a basic MoaT-Link server.
        """
        global _seq  # noqa:PLW0603
        _seq += 1

        s = Server(cfg, f"S_{_seq}", **kw)
        await s.serve(task_status=task_status)

    async def _run_client(self, cfg, *, task_status) -> Never:
        global _seq  # noqa:PLW0603
        _seq += 1

        async with Link(cfg, f"C{_seq}") as li:
            task_status.started(li)
            await anyio.sleep_forever()
            assert False  # noqa:B011,PT015
