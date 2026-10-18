"""Tests for ``moat link code PATH test …`` and ``moat link code : test-all``."""

from __future__ import annotations

import pytest

from moat.util import yload
from moat.lib.path import P
from moat.link._test import Scaffold
from moat.link.code import CODE_EXEC_ROOT
from moat.link.code import _main as code_cmd
from moat.link.code.case import CodeTest, get_test, set_test

pytestmark = pytest.mark.anyio

ADD = "return a + b"

GOOD = """\
info: two plus three
timeout: 5
args: {a: 2, b: 3}
steps:
- [result, "result == 5"]
"""

BAD = """\
info: wrong sum
timeout: 5
args: {a: 2, b: 3}
steps:
- [result, "result == 6"]
"""

SNIP = """\
code: |
  return a + b

info: sum
is_async: true
vars:
- a
- b
tests:
  sum:
    info: two plus three
    args: {a: 2, b: 3}
    steps:
    - [result, "result == 5"]
"""

SNIP2 = """\
code: |
  return a + b

info: sum
is_async: true
vars:
- a
- b
tests:
  sum:
    info: changed
    args: {a: 2, b: 3}
    steps:
    - [result, "result == 5"]
  twice:
    info: doubled
    args: {a: 2, b: 2}
    steps:
    - [result, "result == 4"]
"""

SUM = """\
info: two plus three
args: {a: 2, b: 3}
steps:
- [result, "result == 5"]
"""

SUM_CHANGED = """\
info: changed
args: {a: 2, b: 3}
steps:
- [result, "result == 5"]
"""

TWICE = """\
info: doubled
args: {a: 2, b: 2}
steps:
- [result, "result == 4"]
"""


def _case(text: str) -> CodeTest:
    return CodeTest.model_validate(yload(text))


async def _setup(c):
    await c.d_set(CODE_EXEC_ROOT + P("test.add"), dict(code=ADD, vars=["a", "b"], is_async=True))
    await set_test(c, P("test.add"), P("good"), _case(GOOD))
    await c.i_sync()


async def _fails(sf, cmd: str) -> None:
    "Run a command that must exit with code 1."
    try:
        await sf.run(cmd)
    except BaseException as exc:
        while isinstance(exc, BaseExceptionGroup) and len(exc.exceptions) == 1:
            exc = exc.exceptions[0]
        assert isinstance(exc, SystemExit), exc  # noqa: PT017
        assert exc.code == 1  # noqa: PT017
    else:
        raise AssertionError(f"did not fail: {cmd}")


async def test_crud(cfg, tmp_path):
    "List, set, get and delete test cases"
    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as c,
    ):
        await _setup(c)

        r = await sf.run("link code test.add test")
        assert r.stdout == "good :: two plus three\n"

        # test cases don't show up as snippets
        r = await sf.run("link code test list -s")
        assert r.stdout == "test.add :: <1 lines>\n"

        r = await sf.run("link code test.add test good get")
        assert yload(r.stdout) == yload(GOOD)
        r = await sf.run("link code test.add test good")
        assert yload(r.stdout) == yload(GOOD)

        r = await sf.run("link code test.add test good get -e")
        assert r.stdout.endswith("---\nresult result == 5\n")

        f = tmp_path / "bad.yaml"
        f.write_text(BAD)
        await sf.run(f"link code test.add test bad.sum set -d {f}")
        await c.i_sync()
        assert await get_test(c, P("test.add"), P("bad.sum")) == _case(BAD)

        f = tmp_path / "bad.txt"
        f.write_text("info: edited\n---\nresult result == 7\n")
        await sf.run(f"link code test.add test bad.sum set -e -d {f}")
        await c.i_sync()
        res = await get_test(c, P("test.add"), P("bad.sum"))
        assert res.info == "edited"
        assert res.steps == [["result", "result == 7"]]

        r = await sf.run("link code test.add test")
        assert sorted(r.stdout.splitlines()) == ["bad.sum :: edited", "good :: two plus three"]

        await sf.run("link code test.add test bad.sum delete")
        await c.i_sync()
        with pytest.raises(KeyError):
            await get_test(c, P("test.add"), P("bad.sum"))


async def test_set_routes_tests(cfg, tmp_path):
    """A 'tests' section in ``code set -d`` updates the test cases,
    not the entry."""
    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as c,
    ):
        f = tmp_path / "snip.yaml"
        f.write_text(SNIP)
        await sf.run(f"link code test.snip set -d {f}")
        await c.i_sync()

        body = await c.d_get(CODE_EXEC_ROOT + P("test.snip"))
        assert "tests" not in body
        assert body["code"] == "return a + b\n"
        assert await get_test(c, P("test.snip"), P("sum")) == _case(SUM)

        # a second 'set' modifies the named case and adds a new one
        f.write_text(SNIP2)
        await sf.run(f"link code test.snip set -d {f}")
        await c.i_sync()

        body = await c.d_get(CODE_EXEC_ROOT + P("test.snip"))
        assert "tests" not in body
        assert await get_test(c, P("test.snip"), P("sum")) == _case(SUM_CHANGED)
        assert await get_test(c, P("test.snip"), P("twice")) == _case(TWICE)

        r = await sf.run("link code test.snip test")
        assert sorted(r.stdout.splitlines()) == ["sum :: changed", "twice :: doubled"]

        # the test cases actually run
        r = await sf.run("link code test.snip test - run")
        assert r.stdout.count(": OK (") == 2


async def test_run(cfg):
    "Run one test, all of a snippet's tests, and all tests"
    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as c,
    ):
        await _setup(c)

        r = await sf.run("link code test.add test good run -v")
        assert "good: OK (" in r.stdout
        assert "  result result == 5\n" in r.stdout

        r = await sf.run("link code test.add test - run")
        assert r.stdout.startswith("good: OK (")

        await set_test(c, P("test.add"), P("bad"), _case(BAD))
        await c.d_set(
            CODE_EXEC_ROOT + P("test.sub"),
            dict(code="return a - b", vars=["a", "b"], is_async=True),
        )
        await set_test(
            c,
            P("test.sub"),
            P("one"),
            _case("args: {a: 3, b: 2}\nsteps:\n- [result, 'result == 1']\n"),
        )
        await c.i_sync()

        await _fails(sf, "link code test.add test bad run")
        await _fails(sf, "link code test.add test - run -j 1")
        await _fails(sf, "link code : test-all -j 2")

        r = await sf.run("link code test.sub test-all")
        assert r.stdout == "test.sub: 1 passed, 0 failed\n"

        r = await sf.run("link code test.sub test - run -k")
        assert "root: " in r.stdout


class _Conn:
    def __init__(self, test=None):
        self.test = test
        self.saved = []

    async def d_get(self, path):
        if self.test is None:
            raise KeyError(path)
        return self.test.dump()

    async def d_set(self, path, data):
        self.saved.append((path, data))


async def test_edit_reopens(monkeypatch):
    "A syntax error re-opens the editor with the edited text"
    from io import StringIO  # noqa: PLC0415

    from moat.util import attrdict  # noqa: PLC0415

    texts = []
    answers = iter([
        "info: x\n---\nfrobnicate 1\n",
        "info: x\n---\nsleep 1\n",
    ])

    async def _edit_text(_editor, text, *, suffix):  # noqa: ARG001
        texts.append(text)
        return next(answers)

    async def _prompt(*_a, **_kw):
        return "e"

    monkeypatch.setattr(code_cmd, "edit_text", _edit_text)
    monkeypatch.setattr(code_cmd.click, "prompt", _prompt)

    conn = _Conn()
    obj = attrdict(conn=conn, path=P("foo"), case=P("bar"), stdout=StringIO())
    await code_cmd.case_edit.callback.__wrapped__(obj, editor="dummy")

    assert texts[0] == "---\nstart\n"
    assert texts[1] == "info: x\n---\nfrobnicate 1\n"
    ((path, data),) = conn.saved
    assert path == CODE_EXEC_ROOT + P("foo") / None / "bar"
    assert data == dict(info="x", steps=[["sleep", 1]])


async def test_edit_unchanged(monkeypatch):
    "Saving an unchanged test writes nothing"
    from io import StringIO  # noqa: PLC0415

    from moat.util import attrdict  # noqa: PLC0415

    async def _edit_text(_editor, text, *, suffix):  # noqa: ARG001
        return text

    monkeypatch.setattr(code_cmd, "edit_text", _edit_text)

    conn = _Conn(_case(GOOD))
    obj = attrdict(conn=conn, path=P("foo"), case=P("bar"), stdout=StringIO())
    await code_cmd.case_edit.callback.__wrapped__(obj, editor="dummy")
    assert conn.saved == []
