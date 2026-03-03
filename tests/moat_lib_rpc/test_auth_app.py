"""
Tests for the auth stream app.
"""

from __future__ import annotations

import anyio
import pytest

from moat.util import attrdict
from moat.lib.path import P
from moat.lib.rpc import MsgHandler
from moat.lib.rpc._test import rpc_stack
from moat.lib.rpc.auth._base import AuthDenied

pytestmark = pytest.mark.anyio


CFG_APPS = """
app:
  app: dir
  sec:
    app: auth.Cmd
    auth:
      modes:
      - mode: test
      ok: true
      test:
        ok: true
    cfg:
      app: dir
      inner:
        app: _test_.Cmd
"""


CFG_PATH = """
app:
  app: dir
  inner:
    app: _test_.Cmd
  sec:
    app: auth.Cmd
    path: !P inner
    auth:
      modes:
      - mode: test
      ok: true
      test:
        ok: true
"""


CFG_BAD = """
app:
  app: dir
  sec:
    app: auth.Cmd
    path: !P inner
    auth:
      modes:
      - mode: test
      ok: true
    cfg:
      app: _test_.Cmd
"""


CFG_NOAUTH = """
app:
  app: dir
  sec:
    app: auth.Cmd
    cfg:
      app: _test_.Cmd
"""


class _NullCmd(MsgHandler):
    pass


async def test_auth_app_mode_blocks_direct_access(tmp_path):
    """Direct access to protected local sub-apps is blocked."""
    async with rpc_stack(tmp_path, CFG_APPS) as root:
        with pytest.raises(KeyError):
            await root.cmd(P("sec.inner.echo"), m="hello")


async def test_auth_app_path_redirect_blocks_direct_access(tmp_path):
    """Path redirect mode does not expose direct commands under the auth app."""
    async with rpc_stack(tmp_path, CFG_PATH) as root:
        with pytest.raises(KeyError):
            await root.cmd(P("sec.echo"), m="hello")


async def test_auth_app_rejects_path_plus_cfg(tmp_path):
    """Misconfiguration with both path and cfg is rejected."""
    with pytest.raises(ExceptionGroup) as err:
        async with rpc_stack(tmp_path, CFG_BAD):
            pass
    assert err.group_contains(ValueError)


async def test_auth_app_requires_auth_config(tmp_path):
    """Missing auth config is rejected."""
    with pytest.raises(ExceptionGroup) as err:
        async with rpc_stack(tmp_path, CFG_NOAUTH):
            pass
    assert err.group_contains(ValueError)


async def test_auth_bridge_delegates_and_enforces_auth(monkeypatch):
    """Bridge delegates unauthenticated calls and blocks skipped auth."""
    from moat.lib.rpc.app import auth as auth_app  # noqa: PLC0415

    class _FakeAuth:
        def __init__(self, cfg, parent):
            self.cfg = cfg
            self.parent = parent
            self.process_calls = []
            self.handle_calls = []

        async def process(self, root):
            self.process_calls.append(root)

        async def handle(self, msg, rcmd):
            self.handle_calls.append((msg, tuple(rcmd)))
            return "ok"

    monkeypatch.setattr(auth_app, "Auth", _FakeAuth)

    cfg = attrdict(auth=attrdict(test=attrdict(token="x")))  # noqa:S106
    bridge = auth_app._AuthBridge(  # noqa:SLF001
        cfg,
        object(),
        is_server=True,
        require_remote_auth=True,
    )

    assert bridge.auth.token == "x"

    root = object()
    await bridge.run(root)
    assert bridge._auth.process_calls == [root]  # noqa: SLF001

    res = await bridge.handle("m", ["x"])
    assert res == "ok"

    with pytest.raises(AuthDenied):
        bridge.auth_skip()

    assert await bridge.wait_ready(wait=False) is None


async def test_auth_bridge_stream_dispatch(monkeypatch):
    """Bridge dispatches authenticated calls through the nested stream."""
    from moat.lib.rpc.app import auth as auth_app  # noqa: PLC0415

    class _FakeAuth:
        def __init__(self, cfg, parent):
            self.cfg = cfg
            self.parent = parent

        async def process(self, root):
            root  # noqa: B018

        async def handle(self, msg, rcmd):
            msg  # noqa: B018
            rcmd  # noqa: B018
            return "auth"

    class _FakeStream:
        def __init__(self, _root, _msg, debug=None):
            debug  # noqa: B018
            self.reader_done = anyio.Event()

        async def __aenter__(self):
            self.reader_done.set()
            return self

        async def __aexit__(self, *exc):
            exc  # noqa: B018

        async def handle(self, msg, rcmd):
            return msg, tuple(rcmd)

    monkeypatch.setattr(auth_app, "Auth", _FakeAuth)
    monkeypatch.setattr(auth_app, "CmdStream", _FakeStream)

    bridge = auth_app._AuthBridge(  # noqa:SLF001
        attrdict(auth=attrdict(test=attrdict())),
        object(),
        is_server=True,
        require_remote_auth=False,
    )

    await bridge.process(_NullCmd())
    assert bridge._stream is None  # noqa: SLF001

    bridge._ready.set()  # noqa: SLF001
    bridge._stream = _FakeStream(None, None)  # noqa: SLF001

    res = await bridge.handle("q", ["a"], _auth=True)
    assert res == ("q", ("a",))

    bridge._stream = None  # noqa: SLF001
    with pytest.raises(EOFError):
        await bridge.handle("q", ["a"], _auth=True)
