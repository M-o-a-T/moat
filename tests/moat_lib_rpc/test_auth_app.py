"""
Tests for the auth stream app.
"""

from __future__ import annotations

import pytest

from moat.lib.path import P
from moat.lib.rpc._test import rpc_stack

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
    inner:
      app: _test_.Cmd
"""


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


async def test_auth_app_rejects_path_plus_local_apps(tmp_path):
    """Misconfiguration with both path and local apps is rejected."""
    with pytest.raises(ExceptionGroup) as err:
        async with rpc_stack(tmp_path, CFG_BAD):
            pass
    assert err.group_contains(ValueError)
