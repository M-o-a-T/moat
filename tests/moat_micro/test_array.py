"""
Test the relay implementation
"""

from __future__ import annotations

import pytest

from moat.lib.path import P
from moat.micro._test import mpy_stack

CFG = """
app: dir
c:
  app: cfg.Cmd
a:
  app: sub.Array
  cfg:
    app: _fake.Pin
  1:
    init: true
  n: 3
  i: !P pin
  i_off: 1

"""


@pytest.mark.anyio
async def test_ary(tmp_path):
    "fake array test"
    async with mpy_stack(tmp_path, CFG) as d:  # , d.cfg_at(P("c")) as cf:
        a = d.sub_at(P("a"))
        assert False is (await d.cmd(P("a:0.r")))[0]
        assert True is (await d.cmd(P("a:1.r")))[0]
        assert False is (await d.cmd(P("a:2.r")))[0]
        assert [x[0][0] for x in await a.all("r")] == [False, True, False]
        await a.all("w", True)
        assert [x[0][0] for x in await a.all("r")] == [True, True, True]

        cfg = await d.cmd(P("a:1.cfg_"))
        assert cfg["pin"] == 2

        # TODO change n
