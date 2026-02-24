"""
Connection tests
"""

from __future__ import annotations

import anyio
import pytest
from contextlib import suppress

from moat.util import attrdict, timed_ctx, yload
from moat.lib.micro import Event
from moat.lib.path import P
from moat.lib.rpc._test import rpc_stack
from moat.lib.rpc.auth import token as auth_token

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


CFG2 = """# Tokens
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
      - mode: token
      test:
        token: FooBaR
    log:
      txt: "!L"
  r:
    app: net.unix.Port
    port: /tmp/test.sock
    auth:
      modes:
      - mode: token
      test:
        token:
        - FooBaR
        - fOobAz
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


async def test_token_net(tmp_path):
    "Token auth works end-to-end using test-only injected auth data."
    sock = tmp_path / "test.sock"
    with suppress(FileNotFoundError):
        sock.unlink()

    cfg = yload(CFG2, attr=True)
    cfg.app.r.port = str(sock)
    cfg.app.l.port = str(sock)

    async with timed_ctx(2, rpc_stack(tmp_path, cfg)) as d:
        with anyio.fail_after(2):
            await d.cmd(P("l.!.rdy_"))
            await d.cmd(P("r.!.rdy_"))
        res = await d.cmd(P("l.a.echo"), m="hello")
        assert res.kw == dict(r="hello")


class _AuthParent:
    def __init__(self, *, is_server: bool):
        self.parent = attrdict(is_server=is_server)
        self.accepted = []
        self.denied = []

    def accept(self, sub):
        self.accepted.append(sub.name)

    def deny(self, sub):
        self.denied.append(sub.name)


class _RemoteCall:
    def __init__(self):
        self.calls = []

    async def __call__(self, value):
        self.calls.append(value)


def _token_subauth(*, is_server: bool, auth, fail_invalid: bool = False):
    parent = _AuthParent(is_server=is_server)
    remote = _RemoteCall()
    cfg = attrdict(mode="token")
    if fail_invalid:
        cfg.fail_invalid = True
    sub = auth_token.SubAuth(cfg, auth, parent, 0, "tok", remote)
    sub._seen = Event()  # noqa:SLF001
    return sub, parent, remote


async def test_token_auth_cmd_accepts_matching_token():
    "Token auth accepts a matching token and unblocks the server method."
    sub, parent, _remote = _token_subauth(is_server=True, auth={"sekrit"})

    await sub.cmd("sekrit")

    assert parent.accepted == ["tok"]
    assert parent.denied == []
    assert sub._seen.is_set()  # noqa:SLF001


async def test_token_auth_cmd_ignores_invalid_token_by_default():
    "Token auth ignores invalid tokens unless fail_invalid is enabled."
    sub, parent, _remote = _token_subauth(is_server=True, auth={"sekrit"})

    await sub.cmd("wrong")

    assert parent.accepted == []
    assert parent.denied == []
    assert sub._seen.is_set()  # noqa:SLF001


async def test_token_auth_cmd_denies_invalid_token_if_configured():
    "Token auth denies invalid tokens when fail_invalid is enabled."
    sub, parent, _remote = _token_subauth(is_server=True, auth={"sekrit"}, fail_invalid=True)

    await sub.cmd("wrong")

    assert parent.accepted == []
    assert parent.denied == ["tok"]
    assert sub._seen.is_set()  # noqa:SLF001


async def test_token_auth_client_task_sends_token_and_accepts(monkeypatch):
    "Client token auth sends the configured token and marks the method accepted."
    monkeypatch.setattr(auth_token, "L", False)
    sub, parent, remote = _token_subauth(is_server=False, auth="sekrit")

    await sub.task()

    assert remote.calls == ["sekrit"]
    assert parent.accepted == ["tok"]
    assert parent.denied == []
