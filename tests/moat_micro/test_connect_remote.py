"""
Connection tests
"""

from __future__ import annotations

import pytest

from moat.lib.micro import log, sleep_ms
from moat.lib.path import P, Path
from moat.micro._test import mpy_stack

pytestmark = pytest.mark.anyio


CFG1 = """
app: dir
# l: net.unix.Link
# r: net.unix.Port
a:
  app: _test.Cmd
c:
  app: cfg.Cmd
#l:
#  port: /tmp/test.sock
#r:
#  port: /tmp/test.sock
s:
  app: _test.MpyCmd
  link: &link
    lossy: false
    guarded: false
    frame: 0x85
  cfg:
    app:
      app: dir
      a:
        app: _test.Cmd
      c:
        app: cfg.Cmd
      s:
        app: stdio.StdIO
        link: *link
        log:
          txt: "S"

  log:
    txt: "M"
"""


@pytest.mark.parametrize("server_first", [True, False])
@pytest.mark.parametrize("link_in", [True, False])
@pytest.mark.parametrize("remote_first", [True, False])
async def test_net_r(tmp_path, server_first, link_in, remote_first, free_tcp_port):
    "basic connectivity test"
    log(f"SF={server_first} LI={link_in} RF={remote_first}")
    port = free_tcp_port

    async def set_server(c):
        await c.set({
            "app": {
                "r": {
                    "app": "net.tcp.LinkIn" if link_in else "net.tcp.Port",
                    "host": "127.0.0.1",
                    "port": port,
                    "wait": False,
                },
            },
        })

    async def set_client(c):
        await c.set({
            "app": {
                "r": {
                    "app": "net.tcp.Link",
                    "host": "127.0.0.1",
                    "port": port,
                    "retry": {"delay": 0.2, "timeout": 2},
                    "timeout": 400,
                    "wait": False,
                },
            },
        })

    async with mpy_stack(tmp_path, CFG1) as d, d.cfg_at(P("c")) as cl, d.cfg_at(P("s.c")) as cr:
        if remote_first:
            cl, cr = cr, cl

        await (set_server if server_first else set_client)(cl)
        log("Wait before starting the %s", "client" if server_first else "server")
        await sleep_ms(100)
        await (set_client if server_first else set_server)(cr)
        if (server_first == remote_first, link_in) != (True, False):
            log("Wait Ready remote")
            await d.cmd(P("s.r.!.rdy_"))
        if (server_first == remote_first, link_in) != (False, False):
            log("Wait Ready local")
            await d.cmd(P("r.!.rdy_"))

        async def chk(*p):
            res = await d.cmd(Path.build(p) / "a" / "echo", m="hello")
            assert res.kw == dict(r="hello")

        # if link_in is False, the server supports random connections,
        # thus we can't send commands from the server to the client
        if (server_first == remote_first, link_in) != (False, False):
            log("Check local")
            await chk("r")
        if (server_first == remote_first, link_in) != (True, False):
            log("Check remote")
            await chk("s", "r")
