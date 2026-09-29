"""Tests for `moat.link.gate.run_gates`: supervising all gates below a path."""

from __future__ import annotations

import anyio
import pytest
import sys
from functools import partial

from moat.util import NotGiven
from moat.lib.path import P
from moat.link._test import Scaffold
from moat.link.announce import announcing
from moat.link.exceptions import ServiceSupplanted
from moat.link.gate import run_gates
from moat.link.gate.mqtt import Gate as MqttGate

pytestmark = pytest.mark.anyio

ANN = P("run.host.gate")


def _gate(name: str) -> dict:
    return dict(driver="mqtt", src=P("test.src") / name, dst=P("test.dst") / name, codec="json")


async def _owner(c, name: str):
    "The ID of the client that announces gate @name, or None"
    await c.i_sync()
    try:
        d = await c.d_get(ANN + P(name))
    except KeyError:
        return None
    if d is NotGiven or d is None:
        return None
    return d["id"]


async def _wait_owner(c, name: str, want, up: bool = False) -> None:
    """
    Wait until gate @name is announced by @want (None: not at all).
    With @up, also wait for the gate to be up.
    """
    owner = None
    is_up = False
    with anyio.fail_after(5):
        async with c.d_watch(ANN + P(name), state=None, mark=True) as mon:
            async for d in mon:
                if d is not None:
                    owner = None if d is NotGiven else d["id"]
                    is_up = d is not NotGiven and d.get("up", False)
                if owner == want and (is_up or not up):
                    return


async def test_subtree(cfg):
    "All gates below the path run; new ones start, deleted ones stop"
    async with Scaffold(cfg, use_servers=True) as sf:
        await sf.server(init={"Hello": "there!"})
        c = await sf.client()
        r = await sf.client()
        await c.d_set(P("gate.grp.a"), _gate("a"))
        await c.d_set(P("gate.grp.sub"), dict(info="not a gate"))
        await c.d_set(P("gate.grp.sub.b"), _gate("b"))
        await c.d_set(P("gate.other"), _gate("x"))
        await c.d_set(P("gate.grp.bad"), dict(driver="no.such.driver"))
        await c.i_sync()

        with anyio.fail_after(5):
            await sf.tg.start(run_gates, sf.cfg, r, P("gate.grp"))
        assert await _owner(c, "grp.a") == r.id
        assert await _owner(c, "grp.sub.b") == r.id
        assert await _owner(c, "grp.sub") is None
        assert await _owner(c, "other") is None
        # a broken gate doesn't take the others down
        assert await _owner(c, "grp.bad") is None

        # the gates work
        await c.d_set(P("test.src.a.one"), 1)
        with anyio.fail_after(5):
            async with c.monitor(P("test.dst.a.one"), codec="json") as mon:
                async for msg in mon:
                    assert msg.data == 1
                    break

        # a new gate is started
        await c.d_set(P("gate.grp.c"), _gate("c"))
        await _wait_owner(c, "grp.c", r.id)

        # a deleted gate stops and clears its announcement
        await c.d_set(P("gate.grp.a"))
        await _wait_owner(c, "grp.a", None)


async def test_only(cfg):
    "--only runs just the gate itself"
    async with Scaffold(cfg, use_servers=True) as sf:
        await sf.server(init={"Hello": "there!"})
        c = await sf.client()
        r = await sf.client()
        await c.d_set(P("gate.grp"), _gate("g"))
        await c.d_set(P("gate.grp.a"), _gate("a"))
        await c.i_sync()

        with anyio.fail_after(5):
            await sf.tg.start(partial(run_gates, only=True), sf.cfg, r, P("gate.grp"))
        assert await _owner(c, "grp") == r.id
        assert await _owner(c, "grp.a") is None


async def test_elsewhere(cfg):
    "A gate announced by another service is taken over once that goes away"
    async with Scaffold(cfg, use_servers=True) as sf:
        await sf.server(init={"Hello": "there!"})
        c = await sf.client()
        r = await sf.client()
        o = await sf.client()
        await c.d_set(P("gate.grp.a"), _gate("a"))
        await c.d_set(P("gate.grp.b"), _gate("b"))
        await c.i_sync()

        other_done = anyio.Event()

        async def other(*, task_status):
            async with announcing(o, host=False, name=P("gate.grp.a")) as srv:
                srv.started()
                task_status.started()
                await other_done.wait()

        await sf.tg.start(other)
        await _wait_owner(c, "grp.a", o.id)

        with anyio.fail_after(5):
            await sf.tg.start(run_gates, sf.cfg, r, P("gate.grp"))
        assert await _owner(c, "grp.b") == r.id
        await anyio.sleep(0.3)
        assert await _owner(c, "grp.a") == o.id

        other_done.set()
        await _wait_owner(c, "grp.a", r.id)


async def test_force(cfg):
    "--force takes over gates at startup"
    async with Scaffold(cfg, use_servers=True) as sf:
        await sf.server(init={"Hello": "there!"})
        c = await sf.client()
        r = await sf.client()
        o = await sf.client()
        await c.d_set(P("gate.grp.a"), _gate("a"))
        await c.i_sync()

        async def other(*, task_status):
            try:
                async with announcing(o, host=False, name=P("gate.grp.a")) as srv:
                    srv.started()
                    task_status.started()
                    await anyio.sleep_forever()
            except* ServiceSupplanted:
                pass

        await sf.tg.start(other)
        await _wait_owner(c, "grp.a", o.id)

        with anyio.fail_after(5):
            await sf.tg.start(partial(run_gates, force=True), sf.cfg, r, P("gate.grp"))
        await _wait_owner(c, "grp.a", r.id)
        await anyio.sleep(0.3)
        assert await _owner(c, "grp.a") == r.id


class _Flaky:
    "A gate driver that fails a few times, then works"

    fails = 0

    class Gate(MqttGate):
        async def setup_(self) -> None:
            if _Flaky.fails:
                _Flaky.fails -= 1
                raise RuntimeError("flaky")
            await super().setup_()


async def test_retry(cfg, monkeypatch):
    "A crashed gate is reported, retried with backoff, and reported OK once it runs"
    monkeypatch.setitem(sys.modules, "flaky.gate", _Flaky)
    _Flaky.fails = 2
    cfg.link.gate.backoff = dict(min=0.2, max=0.3, factor=2)
    async with Scaffold(cfg, use_servers=True) as sf:
        await sf.server(init={"Hello": "there!"})
        c = await sf.client()
        r = await sf.client()
        await c.d_set(P("gate.grp.a"), dict(_gate("a"), driver="flaky.gate"))
        await c.i_sync()

        async with c.d_watch(P("error.gate.grp.a"), subtree=True, state=None) as mon:
            with anyio.fail_after(5):
                await sf.tg.start(run_gates, sf.cfg, r, P("gate.grp"))
                # the first failure has been reported by now
                async for _p, d in mon:
                    if "flaky" in str(d):
                        break
                assert await _owner(c, "grp.a") is None

                # two failures later, it runs
                await _wait_owner(c, "grp.a", r.id, up=True)
        assert _Flaky.fails == 0


async def test_retry_on_change(cfg, monkeypatch):
    "A crashed gate is retried at once when its entry changes"
    monkeypatch.setitem(sys.modules, "flaky.gate", _Flaky)
    _Flaky.fails = 1
    cfg.link.gate.backoff = dict(min=100, max=100, factor=2)
    async with Scaffold(cfg, use_servers=True) as sf:
        await sf.server(init={"Hello": "there!"})
        c = await sf.client()
        r = await sf.client()
        await c.d_set(P("gate.grp.a"), dict(_gate("a"), driver="flaky.gate"))
        await c.i_sync()

        with anyio.fail_after(5):
            await sf.tg.start(run_gates, sf.cfg, r, P("gate.grp"))
            assert await _owner(c, "grp.a") is None
            await c.d_set(P("gate.grp.a"), dict(_gate("a"), driver="flaky.gate", info="fixed"))
            await _wait_owner(c, "grp.a", r.id, up=True)
