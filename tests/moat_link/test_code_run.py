"""code runtime tests"""

from __future__ import annotations

import pytest
import threading

from moat.lib.path import P
from moat.link._test import Scaffold
from moat.link.code.run import Code


class _DummyCodeLink:
    def __init__(self, data):
        self.data = data
        self.calls = 0

    async def d_get(self, _path):
        self.calls += 1
        return self.data


@pytest.mark.anyio
async def test_code_at(cfg):
    "Check running code snippets with all async modes."
    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!", "test": 123}),
        sf.client_() as c,
    ):
        await c.d_set(P("test.base"), 41)

        await c.d_set(
            P("code.exec.test.async"),
            dict(
                code="""
assert runner.path == P("code.exec.test.async")
return await link.d_get(P("test.base")) + inc
""",
                vars=dict(inc=0),
                is_async=True,
            ),
        )
        await c.d_set(
            P("code.exec.test.sync"),
            dict(
                code="""
assert link is runner.link
return left + right + len(kw)
""",
                vars=dict(left=0, right=0),
            ),
        )
        await c.d_set(
            P("code.exec.test.thread"),
            dict(
                code="""
import threading
return threading.get_ident() != origin
""",
                vars=dict(origin=0),
                is_async=False,
            ),
        )
        await c.i_sync()

        assert await c.code_at(P("test.sync"))(left=2, right=5) == 9
        assert await c.code_at(P("test.thread"))(origin=threading.get_ident()) is True
        assert await c.code_at(P("test.async"))(inc=1) == 42


@pytest.mark.anyio
async def test_code_loads_once():
    "Code fetches and compiles once, then reuses the cached process."
    link = _DummyCodeLink(dict(code="return base + inc", vars=dict(base=40)))
    code = Code(link, P("code.exec.test.cache"))

    assert await code(inc=1) == 41
    assert await code(inc=2) == 42
    assert link.calls == 1


@pytest.mark.anyio
async def test_code_update_reloads_without_refetch():
    "Code.update replaces data and recompiles from local state."
    link = _DummyCodeLink(dict(code="return value", vars=dict(value=1)))
    code = Code(link, P("code.exec.test.update"))

    assert await code() == 1
    assert link.calls == 1

    code.update(dict(code="return value + 1", vars=dict(value=1)), compile=False)
    assert await code() == 2
    assert link.calls == 1

    code.update(dict(code="return value + 2", vars=dict(value=1)), compile=True)
    assert await code() == 3
    assert link.calls == 1


@pytest.mark.anyio
async def test_code_conditional_return():
    "Conditional returns at module level are honored."
    link = _DummyCodeLink(
        dict(
            code="""
if flag:
    return value + 1
return value + 2
""",
            vars=dict(value=40),
        )
    )
    code = Code(link, P("code.exec.test.cond"))

    assert await code(flag=True) == 41
    assert await code(flag=False) == 42
