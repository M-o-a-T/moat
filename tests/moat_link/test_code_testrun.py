"""Tests for ``moat.link.code.testrun``: running code snippet tests."""

from __future__ import annotations

import anyio
import pytest

from moat.util import yload
from moat.lib.path import P
from moat.link._test import Scaffold
from moat.link.code import CODE_EXEC_ROOT
from moat.link.code.case import CodeTest
from moat.link.code.testroot import ERROR_ROOT
from moat.link.code.testrun import run_test, run_tests

pytestmark = pytest.mark.anyio

COPY = """
await _self.watch(src)
async for msg in _info:
    if isinstance(msg, _cls.ChangeMsg):
        await _link.set(dst, msg.value * factor, idem=True)
"""

BUS = """
await _self.monitor(src)
async for msg in _info:
    if isinstance(msg, _cls.MQTTmsg):
        if msg.value is None:
            return "done"
        await _self.send(dst, msg.value + 1)
"""


def _case(text: str) -> CodeTest:
    return CodeTest.model_validate(yload(text))


async def _code(c, name: str, code: str, vars_=()):
    await c.d_set(
        CODE_EXEC_ROOT + P(name),
        dict(code=code, vars=list(vars_), is_async=True),
    )


async def _gone(c, path) -> bool:
    "Check that nothing is left at @path."
    await c.i_sync()
    try:
        await c.d_get(path)
    except KeyError:
        pass
    else:
        return False
    try:
        async with c.d_walk(path) as mon:
            async for _ in mon:
                return False
    except KeyError:
        pass
    return True


COPY_CASE = """\
info: copy with factor
timeout: 5
data:
  in:
    _: 1
  out:
    _: 0
args:
  src: !P in
  dst: !P out
  factor: 2
steps:
- [monitor, out, !P out]
- [start]
- [wait, 2, "out[-1] == 2"]
- [set, !P in, 5]
- [wait, 2, "out[-1] == 10"]
- [check, "len(out) >= 2 and max(out) == 10"]
"""


async def test_pass(cfg):
    "A passing test; its root is removed afterwards"
    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as c,
    ):
        await _code(c, "test.copy", COPY, ("src", "dst", "factor"))
        res = await run_test(c, P("test.copy"), _case(COPY_CASE))
        assert res.ok, res
        assert res.root is not None
        assert await _gone(c, res.root)


async def test_fail_check(cfg):
    "A failing check reports its step"
    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as c,
    ):
        await _code(c, "test.copy", COPY, ("src", "dst", "factor"))
        case = _case(COPY_CASE)
        case.steps[-1] = ["check", "out[-1] == 11"]
        res = await run_test(c, P("test.copy"), case)
        assert not res.ok
        assert res.step == 6
        assert "out[-1] == 11" in res.message
        assert await _gone(c, res.root)


async def test_wait_timeout(cfg):
    "A wait that times out fails; so does an unknown name"
    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as c,
    ):
        await _code(c, "test.copy", COPY, ("src", "dst", "factor"))
        case = _case(COPY_CASE)
        case.steps[2] = ["wait", 0.3, "out[-1] == 3"]
        res = await run_test(c, P("test.copy"), case)
        assert not res.ok
        assert res.step == 3
        assert "timeout" in res.message

        case = _case(COPY_CASE)
        case.steps[2] = ["check", "nope[-1] == 3"]
        res = await run_test(c, P("test.copy"), case)
        assert not res.ok
        assert res.step == 3
        assert "nope" in res.message


async def test_test_timeout(cfg):
    "The test's own timeout"
    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as c,
    ):
        await _code(c, "test.copy", COPY, ("src", "dst", "factor"))
        case = _case(COPY_CASE)
        case.timeout = 0.5
        case.steps.append(["result"])
        res = await run_test(c, P("test.copy"), case)
        assert not res.ok
        assert "timeout" in res.message
        assert await _gone(c, res.root)


async def test_result(cfg):
    "The snippet's return value"
    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as c,
    ):
        await _code(c, "test.add", "return a + b", ("a", "b"))
        res = await run_test(
            c,
            P("test.add"),
            _case("args: {a: 2, b: 3}\nsteps:\n- [result, 'result == 5']\n"),
        )
        assert res.ok, res
        assert res.result == 5

        res = await run_test(
            c,
            P("test.add"),
            _case("args: {a: 2, b: 3}\nsteps:\n- [result, 'result == 6']\n"),
        )
        assert not res.ok
        assert "result=5" in res.message

        # no steps: the snippet is started, then cancelled
        res = await run_test(c, P("test.add"), _case("args: {a: 2, b: 3}\n"))
        assert res.ok, res


async def test_exception(cfg):
    "A snippet that raises"
    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as c,
    ):
        await _code(c, "test.div", "return a / b", ("a", "b"))
        res = await run_test(
            c,
            P("test.div"),
            _case("args: {a: 2, b: 0}\nsteps:\n- [error, \"'division' in str(error)\"]\n"),
        )
        assert res.ok, res
        assert isinstance(res.error, ZeroDivisionError)

        # not expected
        res = await run_test(c, P("test.div"), _case("args: {a: 2, b: 0}\nsteps:\n- [result]\n"))
        assert not res.ok
        assert "ZeroDivisionError" in res.message

        # the snippet raises while other steps run
        res = await run_test(
            c, P("test.div"), _case("args: {a: 2, b: 0}\nsteps:\n- [sleep, 0.2]\n")
        )
        assert not res.ok
        assert "ZeroDivisionError" in res.message

        # expected, but it didn't
        res = await run_test(c, P("test.div"), _case("args: {a: 2, b: 1}\nsteps:\n- [error]\n"))
        assert not res.ok
        assert "returned 2.0" in res.message


async def test_recorded_error(cfg):
    "_self.error counts as an error, and its record is removed"
    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as c,
    ):
        await _code(c, "test.err", "await _self.error(message='bad')")
        res = await run_test(c, P("test.err"), _case("steps:\n- [error, 'error is not None']\n"))
        assert res.ok, res
        assert await _gone(c, ERROR_ROOT + res.root)


async def test_mqtt(cfg):
    "Raw MQTT: send and monitor"
    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as c,
    ):
        await _code(c, "test.bus", BUS, ("src", "dst"))
        res = await run_test(
            c,
            P("test.bus"),
            _case(
                """\
args:
  src: !P bus.in
  dst: !P bus.out
steps:
- [monitor, out, !P bus.out, mqtt]
- [start]
- [sleep, 0.2]
- [send, !P bus.in, 1]
- [wait, 2, "out == [2]"]
- [send, !P bus.in, 10]
- [wait, 2, "out[-1] == 11"]
- [send, !P bus.in, null]
- [result, "result == 'done'"]
""",
            ),
        )
        assert res.ok, res


async def test_update_delete(cfg):
    "update and delete actions"
    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as c,
    ):
        await _code(c, "test.idle", "import anyio\nawait anyio.sleep(99)")
        res = await run_test(
            c,
            P("test.idle"),
            _case(
                """\
data:
  x:
    _: {a: 1}
steps:
- [monitor, x, !P x]
- [update, !P x, !P b, 2]
- [wait, 2, "x[-1] == {'a': 1, 'b': 2}"]
- [delete, !P x]
- [wait, 2, "x[-1] is None"]
- [check, "len(x) == 3"]
""",
            ),
        )
        assert res.ok, res


async def test_parallel(cfg):
    "Two tests in parallel use separate roots"
    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as c,
    ):
        await _code(c, "test.copy", COPY, ("src", "dst", "factor"))
        a = _case(COPY_CASE)
        b = _case(COPY_CASE)
        b.args["factor"] = 3
        b.steps[2] = ["wait", 2, "out[-1] == 3"]
        b.steps[4] = ["wait", 2, "out[-1] == 15"]
        b.steps[5] = ["check", "max(out) == 15"]

        with anyio.fail_after(10):
            res = await run_tests(c, [("a", P("test.copy"), a), ("b", P("test.copy"), b)])
        assert [k for k, _ in res] == ["a", "b"]
        (_, ra), (_, rb) = res
        assert ra.ok, ra
        assert rb.ok, rb
        assert ra.root != rb.root
