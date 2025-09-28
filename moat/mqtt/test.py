"""
This module contains code that helps with MoaT-KV testing.
"""

from __future__ import annotations

import anyio
from anyio.pytest_plugin import FreePortFactory
from contextlib import asynccontextmanager
from functools import partial
from socket import SOCK_STREAM

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
async def server(mqtt_port: int | None = None, moat_kv_port: int | None = None):
    """
    An async context manager which creates a stand-alone MoaT-KV server.

    The server has a `test_client` method: an async context manager that
    returns a client that's connected to this server.

    Ports are allocated based on the current process's PID.
    """
    if mqtt_port is None:
        mqtt_port = FreePortFactory(SOCK_STREAM)()
    if moat_kv_port is None:
        moat_kv_port = FreePortFactory(SOCK_STREAM)()

    broker_cfg = {
        "listeners": {"default": {"type": "tcp", "bind": f"127.0.0.1:{mqtt_port}"}},
        "timeout-disconnect-delay": 2,
        "auth": {"allow-anonymous": True, "password-file": None},
    }
    server_cfg = {
        "server": {
            "bind_default": {"host": "127.0.0.1", "port": moat_kv_port},
            "backend": "mqtt",
            "mqtt": {"uri": f"mqtt://127.0.0.1:{mqtt_port}/"},
        },
    }

    s = Server(name="gpio_test", cfg=server_cfg, init="GPIO")
    async with create_broker(config=broker_cfg) as broker:
        evt = anyio.Event()
        broker._tg.start_soon(partial(s.serve, ready_evt=evt))  # noqa: SLF001
        await evt.wait()

        s.moat_kv_port = moat_kv_port  # pylint: disable=attribute-defined-outside-init
        yield s


@asynccontextmanager
async def client(mqtt_port: int | None = None, moat_kv_port: int | None = None):
    """
    An async context manager which creates a stand-alone MoaT-KV client.
    """
    async with (
        server(mqtt_port=mqtt_port, moat_kv_port=moat_kv_port) as s,
        s.test_client() as c,
    ):
        yield c
