"""
Websocket connection tests
"""

from __future__ import annotations

import pytest

from moat.lib.micro import sleep_ms
from moat.lib.path import P
from moat.lib.rpc._test import rpc_stack

pytestmark = pytest.mark.anyio

CFG = """
app:
  app: dir
  a:
    app: _test_.Cmd
  c:
    app: cfg.Cmd
"""


@pytest.mark.parametrize("server_first", [True, False])
@pytest.mark.parametrize("link_in", [True, False])
async def test_net_ws(tmp_path, server_first, link_in, free_tcp_port):
    "basic websocket connectivity test"
    port = free_tcp_port
    path = "/rpc"

    async def set_server(c):
        await c.set({
            "app": {
                "r": {
                    "app": "net.ws.LinkIn" if link_in else "net.ws.Port",
                    "host": "127.0.0.1",
                    "port": port,
                    "path": path,
                    "wait": False,
                },
            },
        })

    async def set_client(c):
        await c.set({
            "app": {
                "l": {
                    "app": "net.ws.Link",
                    "host": "127.0.0.1",
                    "port": port,
                    "path": path,
                    "retry": {"delay": 0.02},
                    "timeout": 100,
                    "wait": False,
                },
            },
        })

    async with rpc_stack(tmp_path, CFG) as d, d.cfg_at(P("c")) as c:
        await (set_server if server_first else set_client)(c)
        await sleep_ms(100)
        await (set_client if server_first else set_server)(c)
        await d.cmd(P("l.!.rdy_"))
        await d.cmd(P("r.!.rdy_"))
        res = await d.cmd(P("l.a.echo"), m="hello")
        assert res.kw == dict(r="hello")

        if link_in:
            res = await d.cmd(P("r.a.echo"), m="hello")
            assert res.kw == dict(r="hello")
