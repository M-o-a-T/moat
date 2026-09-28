"""
Tests for the watchdog unit (HEAT.md §3.8).
"""

from __future__ import annotations

import anyio
import pytest

from moat.util import NotGiven, merge, yload
from moat.dev.heat.config import make_config
from moat.dev.heat.emergency import PUMP_SERVICE
from moat.dev.heat.link import out_path
from moat.dev.heat.state import state_path
from moat.dev.heat.watchdog import WatchdogCfg, WatchdogCore, WatchdogState, WatchdogUnit
from moat.lib.path import P
from moat.link.client import Link
from moat.link.host import ServiceMon

from typing import Any

OUT = out_path("watchdog")
UP = {"up": True}
EMERGENCY = {"timeout": 0.5, "max_sensor_age": 5, "total_timeout": 3}
GRACE = {"grace": 0.3}
T_IN, T_OUT = P("heat.s.pump.temp.in"), P("heat.s.pump.temp.out")
FLOW_REQ = P("app.heat.flow.request")
POWER = P("heat.s.pump.cmd.power")


def _core(item: Any = NotGiven) -> WatchdogCore:
    core = WatchdogCore(make_config("watchdog", WatchdogCfg, item), WatchdogState(), 0)
    core.step(_in(pump=None, pump_out=None), -10)  # the pump has been gone for a while
    return core


def _in(**kw: Any) -> dict[str, Any]:
    res: dict[str, Any] = {
        "pump": UP,
        "pump_out": {"run": "run"},
        "pump_state": {"run": 6},
        "passthru": None,
        "disable": None,
    }
    res.update(kw)
    return res


@pytest.mark.parametrize(
    ("kw", "status", "fires"),
    [
        ({}, "watching", False),
        ({"pump": None}, "shutdown", True),
        ({"pump": {"up": False}}, "shutdown", True),
        ({"pump": None, "pump_out": {"run": "temp"}}, "shutdown", True),
        ({"pump": None, "pump_out": {"run": "ice"}}, "shutdown", True),
        ({"pump": None, "pump_out": {"run": "off"}}, "idle", False),
        ({"pump": None, "pump_out": {"run": "down"}}, "idle", False),
        ({"pump": None, "pump_out": None}, "idle", False),
        # the pump unit's own emergency shutdown left its state "off"
        ({"pump": None, "pump_state": {"run": 0}}, "idle", False),
        ({"pump": None, "pump_state": None}, "shutdown", True),
        ({"pump": None, "disable": True}, "disabled", False),
        ({"pump": None, "passthru": "original"}, "passthru", False),
        ({"pump": None, "passthru": "ours"}, "shutdown", True),
    ],
)
def test_decision(kw: dict[str, Any], status: str, fires: bool) -> None:
    "when the watchdog steps in"
    res = _core().step(_in(**kw), 1)
    assert res.outputs[OUT]["status"] == status
    assert (res.act is not None) is fires


def test_grace() -> None:
    "the pump service must be gone for `grace` seconds"
    core = _core()
    core.step(_in(), 0)
    res = core.step(_in(pump=None), 1)
    assert res.act is None
    assert res.outputs[OUT]["status"] == "watching"
    assert res.wake_in == pytest.approx(5)
    assert core.step(_in(pump=UP), 3).act is None
    assert core.step(_in(pump=None), 4).act is None
    assert core.step(_in(pump=None), 8.9).act is None
    assert core.step(_in(pump=None), 9).act is not None


def test_once() -> None:
    "it fires once per pump run, and is re-armed by new pump output"
    core = _core()
    res = core.step(_in(pump=None), 1)
    assert res.act == "pump service gone while run"
    # our own takeover announces the pump service meanwhile
    assert core.step(_in(pump=UP), 2).act is None
    core.done({"reason": res.act, "result": "cooled"})
    res = core.step(_in(pump=None), 3)
    assert res.act is None
    assert res.outputs[OUT] == {
        "status": "done",
        "reason": "pump service gone while run",
        "result": "cooled",
    }
    assert res.save_now
    assert core.state.last == {"reason": "pump service gone while run", "result": "cooled"}
    # a new pump run
    core.step(_in(pump=UP, pump_out={"run": "wait_flow"}), 4)
    assert core.step(_in(pump=None, pump_out={"run": "wait_flow"}), 5).act is None
    res = core.step(_in(pump=None, pump_out={"run": "wait_flow"}), 10)
    assert res.act == "pump service gone while wait_flow"


# on MoaT-Link


async def _setup(heat) -> None:
    await heat.seed_config("emergency", EMERGENCY)
    await heat.seed_config("watchdog", GRACE)
    await heat.feed(T_IN, 30.0)
    await heat.feed(T_OUT, 31.0)


async def _audit(heat, u) -> dict[str, Any]:
    o = await u.wait("out", lambda o: o is not None and "result" in o, timeout=5)
    assert o["reason"] == "pump service gone while run"
    assert o["result"] == "cooled"
    assert o["exit_delta"] == pytest.approx(1.0)
    assert o["duration"] < 3
    st = await u.wait("state", lambda s: s is not None and s.get("last"))
    assert st["last"]["triggered_at"] == o["triggered_at"]
    assert await heat.expect(POWER, lambda v: v == 0) == 0
    await heat.expect(FLOW_REQ, lambda v: v is not None and v["mode"] == "off")
    return o


async def _pump(heat, host: str, *, task_status) -> None:
    "a pump unit that stops announcing itself, as when it is killed"
    async with heat.sf.client_() as c, c.announcing(PUMP_SERVICE, host=host) as srv:
        srv.set()
        await c.d_set(out_path("pump"), {"run": "run"}, retain=True)
        await c.d_set(state_path("pump"), {"run": 6}, retain=True)
        await c.i_sync()
        task_status.started()
        await anyio.sleep(0.5)


@pytest.mark.anyio
async def test_unit_pump_gone(heat) -> None:
    "the pump unit vanishes while running: shutdown, audit record"
    await _setup(heat)
    u = await heat.run_unit(WatchdogUnit)
    await u.wait("out", lambda o: o is not None and o["status"] == "idle")
    await heat.tg.start(_pump, heat, "heat")
    await u.wait("out", lambda o: o["status"] == "watching")
    await _audit(heat, u)
    await u.wait("out", lambda o: o["status"] == "done")
    # the service is released afterwards
    await heat.expect(P("run.host.heat.heat.pump"), lambda v: v is None)


@pytest.mark.anyio
async def test_unit_other_host(heat) -> None:
    "the service host is configured, not this machine's name"
    await heat.seed_config("service", {"host": "heizung"})
    await _setup(heat)
    u = await heat.run_unit(WatchdogUnit)
    await heat.tg.start(_pump, heat, "heizung")
    await u.wait("out", lambda o: o is not None and o["status"] == "watching")
    await _audit(heat, u)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("item", "value", "status"),
    [
        (P("app.heat.watchdog.disable"), True, "disabled"),
        (P("app.heat.passthru.state"), "original", "passthru"),
    ],
)
async def test_unit_inactive(heat, item, value, status) -> None:
    "disabled, or passthru: no action"
    await _setup(heat)
    await heat.feed(item, value)
    u = await heat.run_unit(WatchdogUnit)
    await heat.tg.start(_pump, heat, "heat")
    await heat.expect(P("run.host.heat.heat.pump"), lambda v: v is None, timeout=3)
    await anyio.sleep(0.3)
    assert u.out["status"] == status
    assert "result" not in u.out
    with pytest.raises(KeyError):
        await heat.link.d_get(FLOW_REQ)


@pytest.mark.anyio
async def test_unit_pump_stopped(heat) -> None:
    "the pump unit stopped normally (last run 'off'): no action"
    await _setup(heat)
    u = await heat.run_unit(WatchdogUnit)
    await heat.tg.start(_pump, heat, "heat")
    await heat.feed(out_path("pump"), {"run": "off"})
    await heat.expect(P("run.host.heat.heat.pump"), lambda v: v is None, timeout=3)
    o = await u.wait("out", lambda o: o is not None and o["status"] == "idle")
    assert "result" not in o


# a real crash: the link's service monitor drops the announcement on the WILL

TIMES = """
timeout:
  ping:
    every: .1
    timeout: .2
    delete: .4
    stale: .2
    delay: .05
    down: .15
    min: .9
"""


async def _crashing_pump(heat, *, task_status) -> None:
    link = Link(heat.sf.cfg, "C_pump")
    try:
        async with heat.sf.client_(cli=link) as c, c.announcing(PUMP_SERVICE, host="heat") as srv:
            srv.set()
            await c.d_set(out_path("pump"), {"run": "run"}, retain=True)
            await c.i_sync()
            task_status.started(link)
            await anyio.sleep_forever()
    except* Exception:
        pass  # the crashed client's tasks fail on the dead connection


@pytest.mark.anyio
async def test_unit_pump_crash(heat, cfg) -> None:
    "a crashed pump unit (no clean disconnect): its WILL ends the service, the watchdog acts"
    merge(cfg.link, yload(TIMES, attr=True))
    async with ServiceMon(link=heat.link, cfg=cfg.link):
        await _setup(heat)
        u = await heat.run_unit(WatchdogUnit)
        pump = await heat.tg.start(_crashing_pump, heat)
        await u.wait("out", lambda o: o is not None and o["status"] == "watching")
        # drop the connection without an MQTT DISCONNECT: the broker sends the WILL
        await pump.backend.client._stream.aclose()  # noqa: SLF001
        await _audit(heat, u)
