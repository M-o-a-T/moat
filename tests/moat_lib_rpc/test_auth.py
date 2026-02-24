"""
Connection tests
"""

from __future__ import annotations

import anyio
import pytest
from contextlib import suppress

from moat.util import timed_ctx, yload
from moat.lib.path import P
from moat.lib.rpc._test import rpc_stack

pytestmark = pytest.mark.anyio


CFG1 = """
app:
  app: dir
  a:
    app: _test_.Cmd
  l:
    app: net.unix.Link
    port: /tmp/test.sock
    retry:
      delay: 0.05
    auth:
      modes:
      - mode: test
    log:
      txt: "!L"
  r:
    app: net.unix.Port
    port: /tmp/test.sock
    auth:
      modes:
      - mode: test
    log:
      txt: "!R"
"""


@pytest.mark.parametrize("link_in", [True, False])
async def test_net(tmp_path, link_in):
    "basic connectivity test"
    sock = tmp_path / "test.sock"
    with suppress(FileNotFoundError):
        sock.unlink()

    cfg = yload(CFG1, attr=True)
    cfg.app.r.port = str(sock)
    cfg.app.l.port = str(sock)
    cfg.app.l.auth.ok = True
    if link_in:
        cfg.app.r.app = "net.unix.LinkIn"

    async with timed_ctx(2, rpc_stack(tmp_path, cfg)) as d:
        with anyio.fail_after(2):
            await d.cmd(P("l.!.rdy_"))
            await d.cmd(P("r.!.rdy_"))
        res = await d.cmd(P("l.a.echo"), m="hello")
        assert res.kw == dict(r="hello")

        if link_in:
            res = await d.cmd(P("r.a.echo"), m="hello")
            assert res.kw == dict(r="hello")
