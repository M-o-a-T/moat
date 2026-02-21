from __future__ import annotations  # noqa: D100

import pytest
from io import StringIO

from moat.util import attrdict
from moat.lib.path import P
from moat.link.code import _main as code_cmd
from moat.link.code._main import _check_exec_syntax

_MISSING = object()


class _EditConn:
    def __init__(self, data=_MISSING, template=_MISSING):
        self._data = data
        self._template = template
        self.get_calls = []
        self.search_calls = []
        self.set_calls = []

    async def d_get(self, path):
        self.get_calls.append(path)
        if self._data is _MISSING:
            raise KeyError(path)
        return self._data

    async def d_search(self, path):
        self.search_calls.append(path)
        if self._template is _MISSING:
            raise KeyError(path)
        return self._template

    async def d_set(self, path, data):
        self.set_calls.append((path, data))
        return True


def test_check_exec_syntax_ok():
    "Check compiling a code record with vars and async flag."
    data = dict(
        code="return foo * bar",
        vars=dict(foo=21, bar=2),
        is_async=False,
    )
    _check_exec_syntax(data, P("code.exec.test.mul"))


def test_check_exec_syntax_bad_vars():
    "Reject non-mapping vars configuration."
    data = dict(code="return 1", vars=["x"])
    with pytest.raises(TypeError, match="vars must be a mapping"):
        _check_exec_syntax(data, P("code.exec.test.bad"))


def test_check_exec_syntax_missing_code():
    "Reject records that do not contain code."
    with pytest.raises(KeyError):
        _check_exec_syntax({}, P("code.exec.test.missing"))


@pytest.mark.anyio
async def test_edit_uses_template_fallback(monkeypatch):
    "Edit loads template data when the target path does not exist."

    async def _noop_run(*_a, **_kw):
        return None

    async def _prompt(*_a, **_kw):
        return "s"

    monkeypatch.setattr(code_cmd, "run", _noop_run)
    monkeypatch.setattr(code_cmd.click, "prompt", _prompt)

    conn = _EditConn(template={"code": "return 42;\n"})
    obj = attrdict(conn=conn, path=P("code.exec.foo.bar"), meta=False, stdout=StringIO())

    await code_cmd.edit.callback.__wrapped__(obj, editor="dummy")

    assert [str(p) for p in conn.get_calls] == ["code.exec.foo.bar"]
    assert [str(p) for p in conn.search_calls] == ["template.code.exec.foo.bar"]
    assert conn.set_calls == []


@pytest.mark.anyio
async def test_edit_uses_default_fallback(monkeypatch):
    "Edit falls back to a built-in code snippet if template lookup fails."

    async def _noop_run(*_a, **_kw):
        return None

    async def _prompt(*_a, **_kw):
        return "s"

    monkeypatch.setattr(code_cmd, "run", _noop_run)
    monkeypatch.setattr(code_cmd.click, "prompt", _prompt)

    conn = _EditConn()
    obj = attrdict(conn=conn, path=P("code.exec.foo.bar"), meta=False, stdout=StringIO())

    await code_cmd.edit.callback.__wrapped__(obj, editor="dummy")

    assert [str(p) for p in conn.search_calls] == ["template.code.exec.foo.bar"]
    assert conn.set_calls == []
