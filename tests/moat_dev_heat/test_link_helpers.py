"""
Tests for the heat controller's MoaT-Link helpers.
"""

from __future__ import annotations

import anyio
import pytest

from moat.dev.heat.link import Inputs, Override, Reader, ServiceMonitor, Switch, Writer
from moat.lib.path import P
from moat.util.time import time

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from moat.lib.path import Path
    from moat.link._test import Scaffold
    from moat.link.client import LinkSender

pytestmark = pytest.mark.anyio

TMO = 2


async def _set(link: LinkSender, path: Path, value: Any) -> None:
    await link.d_set(path, value, retain=True, verify=False)


async def test_reader_staleness(link):
    "`Reader.fresh` compares the value's timestamp with the given time"
    path = P("test.heat.r")
    r = Reader[float](link, path)
    async with anyio.create_task_group() as tg:
        await tg.start(r.run)
        assert r.value is None
        assert not r.fresh(time(), 100)

        await _set(link, path, 12.5)
        with anyio.fail_after(TMO):
            assert await r.wait_value() == 12.5
        assert r.ts is not None
        assert r.fresh(time(), 5)
        assert not r.fresh(time() + 10, 5)
        tg.cancel_scope.cancel()


async def test_inputs(link):
    "`Inputs` signals any change and snapshots all values"
    inp = Inputs()
    inp.add("a", Reader[int](link, P("test.heat.a")))
    inp.add("b", Reader[int](link, P("test.heat.b")))
    async with anyio.create_task_group() as tg:
        await tg.start(inp.run)
        assert inp.snapshot() == {"a": None, "b": None}

        await _set(link, P("test.heat.b"), 2)
        with anyio.fail_after(TMO):
            await inp.wait()
        assert inp.snapshot() == {"a": None, "b": 2}
        tg.cancel_scope.cancel()


async def test_writer_dedup(link, monkeypatch):
    "`Writer` skips unchanged values unless forced"
    sent: list[tuple[Path, Any]] = []

    async def d_set(path: Path, value: Any, retain: bool = False) -> None:
        assert retain
        sent.append((path, value))

    monkeypatch.setattr(link, "d_set", d_set)
    w = Writer(link)
    p, q = P("x.y"), P("x.z")
    assert await w.set(p, 1)
    assert not await w.set(p, 1)
    assert await w.set(q, 1)
    assert await w.set(p, 2)
    assert await w.set(p, 2, force=True)
    assert sent == [(p, 1), (q, 1), (p, 2), (p, 2)]


async def test_override(link):
    "tri-state values, mapping form, missing fields, expiry"
    path = P("test.heat.override.wp")
    o = Override[bool](link, path)

    async def put(value: Any) -> None:
        await _set(link, path, value)
        with anyio.fail_after(TMO):
            await o.wait_changed()

    async with anyio.create_task_group() as tg:
        await tg.start(o.run)
        assert o.value is None

        await put(True)
        assert o.value is True
        await put(False)
        assert o.value is False
        await put(None)
        assert o.value is None

        # missing fields: no expiry, no reason
        await put({"value": True})
        assert o.value is True
        assert o.expires is None
        assert o.reason is None

        # already expired on arrival
        await put({"value": True, "expires": time() - 1})
        assert o.value is None

        # expires later
        await put({"value": False, "expires": time() + 0.3, "reason": "test"})
        assert o.value is False
        assert o.reason == "test"
        with anyio.fail_after(TMO):
            await o.wait_changed()
        assert o.value is None

        # a new value cancels the pending expiry
        await put({"value": True, "expires": time() + 0.3})
        await put(True)
        await anyio.sleep(0.5)
        assert o.value is True
        tg.cancel_scope.cancel()


async def test_service_monitor(heat_scaffold: Scaffold, link: LinkSender):
    "`ServiceMonitor` follows the unit's announcement"
    sm = ServiceMonitor(link, "heattest", "pump")
    async with anyio.create_task_group() as tg:
        await tg.start(sm.run)
        assert not sm.alive

        async with (
            heat_scaffold.client_() as c2,
            c2.announcing(P("heat.pump"), host="heattest") as srv,
        ):
            srv.set()
            with anyio.fail_after(TMO):
                while not sm.alive:
                    await sm.wait_changed()

        with anyio.fail_after(TMO):
            while sm.alive:
                await sm.wait_changed()
        tg.cancel_scope.cancel()


def test_switch() -> None:
    "a Switch counts changes by others, not our own"
    r = Switch(None, P("test.sw"))  # ty:ignore[invalid-argument-type]
    r.me = "me"
    r.feed(True, 1, "op")
    assert r.value == (True, 1)
    r.feed(False, 2, "me")
    assert r.own
    assert r.value == (False, 1)
    assert r.differs(True)
    assert not r.differs(False)
    r.feed(True, 3, "op")
    assert r.value == (True, 2)
    r.feed(None, 4, "op")
    assert r.value == (None, 3)
