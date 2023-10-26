"""
Test the relay implementation
"""
from __future__ import annotations

import pytest

from moat.micro._test import mpy_stack

CFG = """
apps:
  a: sub.Array
  c: cfg.Cmd
a:
  app: _fake.Pin
  cfg: {}
  n: 3
  i: !P pin
  i_off: 1
  1:
    init: true

"""


@pytest.mark.anyio()
async def test_ary(tmp_path):
    "fake array test"
    async with mpy_stack(tmp_path, CFG) as d:  # , d.cfg_at("c") as cf:
        a = d.sub_at("a")
        assert False is await d.send("a", 0, "r")
        assert True is await d.send("a", 1, "r")
        assert False is await d.send("a", 2, "r")
        assert [False, True, False] == await a.all("r")
        await a.all("w", d={"v": True})
        assert [True, True, True] == await a.all("r")

        cfg = await d.send("a", 1, "cfg")
        assert cfg["pin"] == 2

        # TODO change n
