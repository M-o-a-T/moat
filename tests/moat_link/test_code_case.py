"""Tests for code snippet test cases (`moat.link.code.case`)."""

from __future__ import annotations

import pytest
from io import StringIO

from pydantic import ValidationError

from moat.util import attrdict, yload
from moat.lib.path import P
from moat.link._test import Scaffold
from moat.link.code import CODE_EXEC_ROOT
from moat.link.code._main import _list_entries
from moat.link.code.case import CodeTest, del_test, get_test, is_test_path, list_tests, set_test

CASE = """
info: copy a value
timeout: 10
data:
  in:
    _: 1
  out:
    _: 0
args:
  src: !P in
  dst: !P out
  seconds: 0.2
steps:
- [monitor, out, !P out]
- [start]
- [set, !P in, 2]
- [wait, 1, "out[-1] == 2"]
- [check, "len(out) == 2"]
"""


def test_model_defaults():
    "An empty record is a valid test case; defaults are not stored."
    t = CodeTest.model_validate({})
    assert t.timeout == 30
    assert t.steps == []
    assert t.dump() == {}


@pytest.mark.parametrize(
    "rec",
    [
        dict(steps=[["frobnicate"]]),
        dict(steps=[[]]),
        dict(steps=[["check"]]),
        dict(timeout=0),
        dict(code="return 1"),
    ],
)
def test_model_rejects(rec):
    "Bad steps, bad timeouts and unknown keys are rejected."
    with pytest.raises(ValidationError):
        CodeTest.model_validate(rec)


def test_is_test_path():
    "The ``:n`` element marks a snippet's tests."
    assert is_test_path(P("transform.copy:n.basic"))
    assert not is_test_path(P("transform.copy.value"))


@pytest.mark.anyio
async def test_storage(cfg):
    "Test cases round-trip through Link and are hidden from ``code list``."
    t = CodeTest.model_validate(yload(CASE))
    snip = P("transform.copy")
    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as c,
    ):
        await c.d_set(CODE_EXEC_ROOT + snip, dict(code="return 1", info="copy"))
        await c.d_set(CODE_EXEC_ROOT + snip / "value", dict(code="return 2", info="value"))
        await set_test(c, snip, P("basic"), t)
        await set_test(c, snip, P("more.info"), CodeTest(info="two"))

        assert await get_test(c, snip, P("basic")) == t
        assert await c.d_get(CODE_EXEC_ROOT + P("transform.copy:n.basic")) == t.dump()
        assert [(n, x.info) async for n, x in list_tests(c, snip)] == [
            (P("basic"), "copy a value"),
            (P("more.info"), "two"),
        ]
        assert [n async for n, _ in list_tests(c, snip / "value")] == []

        out = StringIO()
        obj = attrdict(conn=c, path=P("transform"), stdout=out)
        await _list_entries(obj, None, None, None, False, True)
        assert out.getvalue().splitlines() == [
            "transform.copy :: copy",
            "transform.copy.value :: value",
        ]

        await del_test(c, snip, P("basic"))
        with pytest.raises(KeyError):
            await get_test(c, snip, P("basic"))
