"""
Connection tests
"""

from __future__ import annotations

import os
import pytest
from contextlib import suppress

from moat.micro._test import mpy_stack
from moat.util.compat import sleep_ms
from moat.util import P

pytestmark = pytest.mark.anyio

# step 1, locally

CFG1 = """
apps:
# l: net.unix.Link
# r: net.unix.Port
  a: _test.Cmd
  c: cfg.Cmd
#l:
#  port: /tmp/test.sock
#r:
#  port: /tmp/test.sock
"""


@pytest.mark.parametrize("server_first", [True, False])
@pytest.mark.parametrize("link_in", [True, False])
@pytest.mark.parametrize("unix", [False, True])
async def test_net(tmp_path, server_first, link_in, unix, free_tcp_port):
    "basic connectivity test"
    if unix:
        sock = tmp_path / "test.sock"
        with suppress(FileNotFoundError):
            sock.unlink()
    else:
        port = free_tcp_port

    async def set_server(c):
        if unix:
            await c.set(
                {
                    "apps": {"r": "net.unix.LinkIn" if link_in else "net.unix.Port"},
                    "r": {"port": str(sock), "wait": False},
                },
                sync=True,
            )
        else:
            await c.set(
                {
                    "apps": {"r": "net.tcp.LinkIn" if link_in else "net.tcp.Port"},
                    "r": {"host": "127.0.0.1", "port": port, "wait": False},
                },
                sync=True,
            )

    async def set_client(c):
        await c.set(
            {
                #           "apps": {"l": "net.unix.Link"},
                #           "l": {"port": str(sock)},
                "apps": {"l": "sub.Err"},
                "l": {
                    "app": "net.unix.Link" if unix else "net.tcp.Link",
                    "cfg": {"port": str(sock)} if unix else {"host": "127.0.0.1", "port": port},
                    "retry": 9,
                    "timeout": 100,
                    "wait": False,
                },
            },
            sync=True,
        )

    async with mpy_stack(tmp_path, CFG1) as d, d.cfg_at(P("c")) as c:
        await (set_server if server_first else set_client)(c)
        await sleep_ms(100)
        await (set_client if server_first else set_server)(c)
        await d.cmd("l.!rdy_")
        await d.cmd("r.!rdy_")
        res = await d.cmd(P("l.a.echo"), m="hello")
        assert res.kw == dict(r="hello")

        if link_in:
            res = await d.cmd(P("r.a.echo"), m="hello")
            assert res.kw == dict(r="hello")
