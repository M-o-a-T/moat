"""
Tests for the pump unit's MoaT-Link adapter (HEAT.md §2.5, §2.6, §3.4):
abnormal exits run the emergency shutdown, a supplanted unit doesn't,
and a restart resumes where the unit left off.
"""

from __future__ import annotations

import anyio
import pytest

from moat.dev.heat.config import EmergencyCfg
from moat.dev.heat.emergency import emergency_shutdown
from moat.dev.heat.link import out_path
from moat.dev.heat.pid import T_OFFSET
from moat.dev.heat.pump import PumpAbort, PumpCore, PumpState, PumpUnit, Run
from moat.dev.heat.state import state_path
from moat.lib.path import P
from moat.link.exceptions import ServiceSupplanted

from typing import Any

pytestmark = pytest.mark.anyio

POWER = P("heat.s.pump.cmd.power")
MODE = P("heat.s.pump.cmd.mode")
FLOW = P("app.heat.flow.request")
STATE = state_path("pump")
OUT = out_path("pump")
DEMAND = {"t_nom": 50, "t_low": 52, "t_adj": 52, "t_set_on": 50, "t_set_off": 51, "source": "heat"}
SENSORS = {
    "heat.s.pump.temp.in": 30.0,
    "heat.s.pump.temp.out": 36.0,
    "heat.s.pump.flow": 15.0,
    "heat.s.pump.power": 2.0,
    "heat.s.pump.de_ice": False,
    "heat.s.buffer.temp.water": 40.0,
    "heat.s.buffer.temp.heat": 38.0,
    "heat.s.buffer.temp.mid": 36.0,
    "heat.s.buffer.temp.return": 30.0,
    "heat.s.heating.temp.out": 35.0,
    "heat.s.heat.temp": 45,
    "heat.s.water.temp": 50,
}


class Pump:
    "runs the pump unit on its own client; keeps the exception it ended with"

    def __init__(self, heat) -> None:
        self.heat = heat
        self.exc: BaseException | None = None
        self.done = anyio.Event()
        self.scope: anyio.CancelScope | None = None

    async def _run(self, *, task_status) -> None:
        # the client stays up while the unit is cancelled, as it must for
        # the shutdown to work
        async with self.heat.sf.client_() as c:
            try:
                with anyio.CancelScope() as self.scope:
                    await PumpUnit(c, save_delay=0.1).run(task_status=task_status)
            except Exception as exc:
                self.exc = exc
            finally:
                self.done.set()

    async def start(self) -> None:
        "start the unit"
        await self.heat.tg.start(self._run)

    async def stop(self) -> BaseException | None:
        "cancel the unit and wait until it has ended"
        assert self.scope is not None
        self.scope.cancel()
        return await self.ended()

    async def ended(self, timeout: float = 15) -> BaseException | None:
        "wait until the unit has ended"
        with anyio.fail_after(timeout):
            await self.done.wait()
        return self.exc


async def _setup(heat, run: Run = Run.run, **pump: Any) -> None:
    "a cold buffer, sensors of a running heat pump, a saved state, short timeouts"
    for p, v in SENSORS.items():
        await heat.feed(P(p), v)
    await heat.feed(out_path("target"), {"flow_temp": 45.0, "demand": DEMAND})
    await heat.seed_config("emergency", {"timeout": 1, "total_timeout": 5})
    if pump:
        await heat.seed_config("pump", pump)
    st = PumpState(run=run, load_last=0.5)
    await heat.feed(STATE, st.model_dump(context={T_OFFSET: 0}))


async def _shut_down(heat) -> None:
    "the emergency procedure ran: heat pump off, water pump stopped, state off"
    assert await heat.expect(POWER, lambda v: v == 0) == 0
    assert await heat.expect(MODE, lambda v: v == 0) == 0
    flow = await heat.expect(FLOW, lambda v: v is not None and v["mode"] == "off")
    assert flow["mode"] == "off"
    st = await heat.expect(STATE, lambda v: v is not None and v["run"] == Run.off)
    assert st["load_last"] is None


async def test_restart_resumes(heat):
    "a restart in 'run' continues running, with the saved load"
    await _setup(heat)
    p = Pump(heat)
    await p.start()
    out = await heat.expect(OUT, lambda v: v is not None and v["run"] == "run")
    assert out["load"] == pytest.approx(0.5, abs=0.3)
    assert p.exc is None
    await p.stop()


async def test_errors(heat):
    "a critical error while running: emergency shutdown, then PumpAbort"
    await _setup(heat)
    p = Pump(heat)
    await p.start()
    await heat.expect(OUT, lambda v: v is not None and v["run"] == "run")
    await heat.feed(out_path("errors"), {"errors": {":3": 99}, "severity": "critical"})
    exc = await p.ended()
    assert isinstance(exc, BaseExceptionGroup)
    assert exc.subgroup(PumpAbort) is not None
    await _shut_down(heat)


async def test_warning_is_no_abort(heat):
    "a warning just stops the heat pump the normal way"
    await _setup(heat)
    p = Pump(heat)
    await p.start()
    await heat.expect(OUT, lambda v: v is not None and v["run"] == "run")
    await heat.feed(out_path("errors"), {"errors": {":3": 99}, "severity": "warning"})
    await heat.expect(OUT, lambda v: v["run"] in ("down", "off"))
    assert p.exc is None
    await p.stop()


async def test_stale_sensor(heat):
    "a sensor that stops changing while running: emergency shutdown"
    await _setup(heat, stale=1, stale_sensors=["t_in"])
    p = Pump(heat)
    await p.start()
    exc = await p.ended()
    assert exc is not None
    assert exc.subgroup(PumpAbort) is not None
    await _shut_down(heat)


async def test_exception(heat, monkeypatch):
    "any other exception: emergency shutdown, then the exception"
    await _setup(heat)
    p = Pump(heat)
    await p.start()
    await heat.expect(OUT, lambda v: v is not None and v["run"] == "run")

    def boom(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("boom")

    monkeypatch.setattr(PumpCore, "step", boom)
    await heat.feed(P("heat.s.pump.temp.out"), 37.0)
    exc = await p.ended()
    assert exc is not None
    assert exc.subgroup(RuntimeError) is not None
    await _shut_down(heat)


async def test_cancel(heat):
    "cancelled while running: the shutdown runs shielded"
    await _setup(heat)
    p = Pump(heat)
    await p.start()
    await heat.expect(OUT, lambda v: v is not None and v["run"] == "run")
    assert await p.stop() is None
    await _shut_down(heat)


async def test_off_when_idle(heat):
    "ending while off: nothing to shut down"
    await _setup(heat, run=Run.off)
    await heat.feed(P("heat.s.pump.temp.out"), 30.0)  # cool: a restart's 'down' ends at once
    await heat.feed(P("app.heat.override.wp"), False)  # and doesn't start again
    p = Pump(heat)
    await p.start()
    await heat.expect(OUT, lambda v: v is not None and v["run"] == "off")
    await heat.feed(FLOW, {"mode": "fixed", "pwm": 0.3, "seq": 99})
    await p.stop()
    assert (await heat.expect(FLOW, lambda v: v is not None))["seq"] == 99


async def test_supplant(heat):
    "'moat dev heat off' takes over: the unit exits without its own shutdown"
    await _setup(heat)
    p = Pump(heat)
    await p.start()
    await heat.expect(OUT, lambda v: v is not None and v["run"] == "run")

    drains: list[int] = []

    async def watch(*, task_status) -> None:
        async with heat.link.d_watch(FLOW, state=False) as mon:
            task_status.started()
            async for v in mon:
                if v["mode"] == "drain":
                    drains.append(v["seq"])

    await heat.tg.start(watch)
    cfg = EmergencyCfg(timeout=1, total_timeout=5)
    await emergency_shutdown(heat.link, cfg, from_pump=False)
    exc = await p.ended()
    assert exc is not None
    assert exc.subgroup(ServiceSupplanted) is not None
    await anyio.sleep(0.5)
    assert len(drains) == 1


async def test_override_off(heat):
    "override False while running: a normal stop, no exception"
    await _setup(heat)
    p = Pump(heat)
    await p.start()
    await heat.expect(OUT, lambda v: v is not None and v["run"] == "run")
    await heat.feed(P("app.heat.override.wp"), False)
    out = await heat.expect(OUT, lambda v: v["run"] in ("down", "off"))
    assert out["reason"] == "override"
    assert p.exc is None
    await p.stop()
