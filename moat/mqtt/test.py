"""
This module contains code that helps with MoaT-KV testing.
"""

from __future__ import annotations

import anyio
from contextlib import asynccontextmanager
from functools import partial

from moat.kv.client import client_scope, open_client
from moat.kv.server import Server as _Server

from .broker import create_broker


class Server(_Server):  # noqa: D101
    @asynccontextmanager
    async def test_client(self, name=None):
        """
        An async context manager that returns a client that's connected to
        this server.
        """
        async with open_client(
            conn=dict(host="127.0.0.1", port=self.moat_kv_port, name=name),
        ) as c:
            yield c

    async def test_client_scope(self, name=None):  # noqa: D102
        return await client_scope(conn=dict(host="127.0.0.1", port=self.moat_kv_port, name=name))


@asynccontextmanager
async def server():
    """
    An async context manager which creates a stand-alone MoaT-KV server.

    The server has a `test_client` method: an async context manager that
    returns a client that's connected to this server.

    Both the MQTT broker and the MoaT-KV server bind to port 0; the
    OS-assigned ports are read back after startup.
    """
    broker_cfg = {
        "listeners": {"default": {"type": "tcp", "bind": "127.0.0.1:0"}},
        "timeout-disconnect-delay": 2,
        "auth": {"allow-anonymous": True, "password-file": None},
    }
    server_cfg = {
        "server": {
            "bind_default": {"host": "127.0.0.1", "port": 0},
            "backend": "mqtt",
            "mqtt": {"uri": None},  # filled in after the broker starts
        },
    }

    async with create_broker(config=broker_cfg) as broker:
        # Read back the broker's OS-assigned port and fill in the URI.
        mqtt_port = broker._servers["default"].port  # noqa: SLF001
        server_cfg["server"]["mqtt"]["uri"] = f"mqtt://127.0.0.1:{mqtt_port}/"

        s = Server(name="gpio_test", cfg=server_cfg, init="GPIO")
        evt = anyio.Event()
        broker._tg.start_soon(partial(s.serve, ready_evt=evt))  # noqa: SLF001
        await evt.wait()

        # Read back the kv server's OS-assigned port.
        s.moat_kv_port = s.ports[0][1]  # pylint: disable=attribute-defined-outside-init
        yield s


@asynccontextmanager
async def client():
    """
    An async context manager which creates a stand-alone MoaT-KV client.
    """
    async with (
        server() as s,
        s.test_client() as c,
    ):
        yield c
