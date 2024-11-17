from __future__ import annotations

import anyio
import logging
import os
import time
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path

from mqttproto.async_broker import AsyncMQTTBroker

from moat.lib.cmd import CmdHandler
from moat.link.client import Link
from moat.link.server import Server
from moat.util import (  # pylint:disable=no-name-in-module
    CtxObj,
    attrdict,
    combine_dict,
    yload,
)

CFG = yload(Path(__file__).parent / "_config.yaml", attr=True)


logger = logging.getLogger(__name__)

otm = time.time

PORT = 40000 + (os.getpid() + 10) % 10000

broker_cfg = {
    "listeners": {"default": {"type": "tcp", "bind": f"127.0.0.1:{PORT}"}},
    "timeout-disconnect-delay": 2,
    "auth": {"allow-anonymous": True, "password-file": None},
}

URI = f"mqtt://127.0.0.1:{PORT}/"


# TODO launch a "real" broker instead

logger = logging.getLogger(__name__)


async def run_broker(cfg, *, task_status):
    """
    Runs a basic MQTT broker.

    The task status returns the port we're listening on.
    """
    broker = AsyncMQTTBroker(("127.0.0.1", 0))

    await broker.serve(task_status=task_status)


class Scaffold(CtxObj):
    def __init__(self, cfg: attrdict, use_servers=True):
        self.cfg = cfg.link

        self.cfg.setdefault("backend", attrdict())
        self.cfg.backend.setdefault("driver", "mqtt")
        self.cfg.backend.setdefault("codec", "std-cbor")

        if not use_servers:
            self.cfg.client.init_timeout = None

    @asynccontextmanager
    async def _ctx(self):
        async with (
            anyio.create_task_group() as tg,
            AsyncExitStack() as ex,
        ):
            self.tg = tg
            bport = await tg.start(run_broker, self.cfg)

            self.cfg.backend.port = bport
            yield self
            tg.cancel_scope.cancel()

    async def server(self, cfg: dict | None = None) -> Server:
        cfg = combine_dict(cfg, self.cfg) if cfg else self.cfg
        return await self.tg.start(self._run_server, cfg)

    async def client(self, cfg: dict | None = None):
        cfg = combine_dict(cfg, self.cfg) if cfg else self.cfg
        return await self.tg.start(self._run_client, cfg)

    async def _run_server(self, cfg, *, task_status) -> Never:
        """
        Runs a basic MoaT-Link server.
        """

        PORT = 40000 + (os.getpid() + 22) % 10000

        async def rdl():
            pass

        async def rdr(client):
            cmd = CmdHandler(cmdh)
            async with anyio.create_task_group() as tg:
                tg.start_soon(rdl)
                tg.start_soon(wrl)

        listener = await create_tcp_listener(local_host="127.0.0.1")
        port = listener.extra(anyio.abc.SocketAttribute.local_port)
        task_status.started((port, cs))
        await listener.serve(rdr)

    async def _run_client(self, cfg, *, task_status) -> Never:
        async with Link(cfg) as li:
            task_status.started(li)
            await anyio.Event().wait()
            assert False
