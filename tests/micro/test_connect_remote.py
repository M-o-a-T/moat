"""
Connection tests
"""

from __future__ import annotations

import os
import pytest

from moat.micro._test import mpy_stack
from moat.micro.compat import log, sleep_ms
from moat.util import P

pytestmark = pytest.mark.anyio


CFG1 = """
apps:
# l: net.unix.Link
# r: net.unix.Port
  s: _test.MpyCmd
  a: _test.Cmd
  c: cfg.Cmd
#l:
#  port: /tmp/test.sock
#r:
#  port: /tmp/test.sock
s:
  mplex: true
  link: &link
    lossy: False
    guarded: False
  cfg:
    apps:
      a: _test.Cmd
      c: cfg.Cmd
      s: stdio.StdIO
    s:
      link: *link
      log:
        txt: "S"

  log:
    txt: "M"
"""


@pytest.mark.parametrize("server_first", [True, False])
@pytest.mark.parametrize("link_in", [True, False])
@pytest.mark.parametrize("remote_first", [True, False])
async def test_net_r(tmp_path, server_first, link_in, remote_first):
    "basic connectivity test"
    log(f"SF={server_first} LI={link_in} RF={remote_first}")
    port = 50000 + os.getpid() % 10000

    async def set_server(c):
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
                "apps": {"r": "sub.Err"},
                "r": {
                    "app": "net.tcp.Link",
                    "cfg": {"host": "127.0.0.1", "port": port},
                    "retry": 10,
                    "timeout": 400,
                    "wait": False,
                },
            },
            sync=True,
        )

    async with mpy_stack(tmp_path, CFG1) as d, d.cfg_at(P("c")) as cl, d.cfg_at(P("s.c")) as cr:
        if remote_first:
            cl, cr = cr, cl  # noqa:PLW2901

        await (set_server if server_first else set_client)(cl)
        log("Wait before starting the %s", "client" if server_first else "server")
        await sleep_ms(100)
        await (set_client if server_first else set_server)(cr)
        if (server_first == remote_first, link_in) != (True, False):
            while await d.send("s", "r", "?rdy_"):
                await sleep_ms(100)
        if (server_first == remote_first, link_in) != (False, False):
            while await d.send("r", "?rdy_"):
                await sleep_ms(100)

        async def chk(*p):
            res = await d.send(*p, "a", "echo", m="hello")
            assert res == dict(r="hello")

        # if link_in is False, the server supports random connections,
        # thus we can't send commands from the server to the client
        if (server_first == remote_first, link_in) != (False, False):
            await chk("r")
        if (server_first == remote_first, link_in) != (True, False):
            await chk("s", "r")
