"""
Test the relay implementation
"""

from __future__ import annotations

import pytest

from moat.util import yload, P
from moat.micro._test import mpy_stack

CFGW = """
apps:
  a: _test.LoopLink
  b: _test.LoopLink
  c: _test.LoopLink
a:
  path: !P b
  usage: mbsc
b:
  path: !P c
  usage: mbsc
c:
  path: !P a
  usage: mbsc
"""

CFGR = """
apps:
  a: _test.LoopLink
  b: _test.LoopLink
  c: _test.LoopLink
a:
  path: !P c
  usage: MBSC
b:
  path: !P a
  usage: MBSC
c:
  path: !P b
  usage: MBSC
"""


@pytest.mark.parametrize("cfg", [yload(CFGW), yload(CFGR)])
@pytest.mark.anyio()
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

        assert (await a.r()) == "a"
        assert (await b.r()) == "b"
        assert (await c.r()) == "c"

        assert (await a.rd()) == b"as"
        assert (await b.rd()) == b"bs"
        assert (await c.rd()) == b"cs"

        assert (await a.crd()) == b"ac"
        assert (await b.crd()) == b"bc"
        assert (await c.crd()) == b"cc"

        assert (await a.rb()) == "ab"
        assert (await b.rb()) == "bb"
        assert (await c.rb()) == "cb"


CFGL = """
apps:
  a: _test.LoopMsg
  b: _test.LoopLink
a:
  path: !P b
b:
  usage: mbscMBSC
"""


@pytest.mark.anyio()
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

        assert (await a.r()) == "a"
        assert (await b.r()) == "b"

        assert (await a.rd(5)) == b"as"
        assert (await b.rd(5)) == b"bs"

        assert (await a.crd(5)) == b"ac"
        assert (await b.crd(5)) == b"bc"

        assert (await a.rb()) == "ab"
        assert (await b.rb()) == "bb"
