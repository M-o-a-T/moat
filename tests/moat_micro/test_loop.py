"""
Test the relay implementation
"""

from __future__ import annotations

import pytest

from moat.util import yload
from moat.lib.path import P
from moat.micro._test import mpy_stack

CFGW = """
app: dir
a:
  app: _test.LoopLink
  path: !P b
  usage: mbsc
b:
  app: _test.LoopLink
  path: !P c
  usage: mbsc
c:
  app: _test.LoopLink
  path: !P a
  usage: mbsc
"""

CFGR = """
app: dir
a:
  app: _test.LoopLink
  path: !P c
  usage: MBSC
b:
  app: _test.LoopLink
  path: !P a
  usage: MBSC
c:
  app: _test.LoopLink
  path: !P b
  usage: MBSC
"""


@pytest.mark.parametrize("cfg", [yload(CFGW), yload(CFGR)])
@pytest.mark.anyio
async def test_loop(tmp_path, cfg):
    "relay test"
    async with mpy_stack(tmp_path, cfg) as d:
        a = d.sub_at(P("a"))
        b = d.sub_at(P("b"))
        c = d.sub_at(P("c"))

        await a.s("c")
        await b.s("a")
        await c.s("b")

        await a.wr(b"cs")
        await b.wr(b"as")
        await c.wr(b"bs")

        await a.cwr(b"cc")
        await b.cwr(b"ac")
        await c.cwr(b"bc")

        await a.sb("cb")
        await b.sb("ab")
        await c.sb("bb")

        assert await a.r() == "a"
        assert await b.r() == "b"
        assert await c.r() == "c"

        assert await a.rd() == b"as"
        assert await b.rd() == b"bs"
        assert await c.rd() == b"cs"

        assert await a.crd() == b"ac"
        assert await b.crd() == b"bc"
        assert await c.crd() == b"cc"

        assert await a.rb() == "ab"
        assert await b.rb() == "bb"
        assert await c.rb() == "cb"


CFGL = """
app: dir
a:
  app: _test.LoopMsg
  path: !P b
b:
  app: _test.LoopLink
  usage: mbscMBSC
"""


@pytest.mark.anyio
async def test_loopmsg(tmp_path):
    "relay test"
    async with mpy_stack(tmp_path, CFGL) as d:
        a = d.sub_at(P("a"))
        b = d.sub_at(P("b"))

        await a.s("b")
        await b.s("a")

        await a.wr(b"bs")
        await b.wr(b"as")

        await a.cwr(b"bc")
        await b.cwr(b"ac")

        await a.sb("bb")
        await b.sb("ab")

        assert await a.r() == "a"
        assert await b.r() == "b"

        assert await a.rd(5) == b"as"
        assert await b.rd(5) == b"bs"

        assert await a.crd(5) == b"ac"
        assert await b.crd(5) == b"bc"

        assert await a.rb() == "ab"
        assert await b.rb() == "bb"
