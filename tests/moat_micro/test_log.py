"""
Check the logging app
"""

from __future__ import annotations

import pytest

from moat.util import yload
from moat.lib.path import P
from moat.lib.rpc import MsgSender
from moat.micro._test import mpy_stack

pytestmark = pytest.mark.anyio

TT = 100  # XXX depends on how much we're logging

CFG = """
app:
  app: dir
  # r: _test.MpyCmd
  a:
    app: log.Cmd
    cfg:
      app: _test.Cmd
  b:
    app: _test.Cmd
"""


async def test_crash(tmp_path):
    "basic error handling test"
    cfg = yload(CFG, attr=True)
    async with mpy_stack(tmp_path, cfg, run=True) as d:
        s = MsgSender(d)
        s.add_sub("a")
        s.add_sub("b")

        res = await s.a.echo(m="hello A")
        assert res == dict(r="hello A")

        res = await s.b.echo(m="hello B")
        assert res == dict(r="hello B")

        res = await s.a.run(P("b.echo"), m="hello AB")
        assert res == dict(r="hello AB")

        res = await s.b.run(P("a.echo"), m="hello BA")
        assert res == dict(r="hello BA")
