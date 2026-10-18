"""
End-to-end scenarios: all heat units and the plant simulator on MoaT-Link
(HEAT.md §5.1, layer 3), in simulated time.

The scenarios are short (at most about 15 simulated minutes) and marked
``slow``; the long ones run in the closed loop (``test_closed_loop.py``).
"""

from __future__ import annotations

import anyio
import pytest
from contextlib import AsyncExitStack, ExitStack, suppress
from functools import partial
from time import time as _real_time
from unittest.mock import patch

import trio

from moat.dev.heat.link import out_path
from moat.dev.heat.override import OVERRIDE_PATH as OVR
from moat.dev.heat.override import set_override
from moat.dev.heat.pump import PumpUnit, set_force_start
from moat.dev.heat.sim.link import SimLink
from moat.dev.heat.sim.scenario import Scenario
from moat.dev.heat.system.runner import DEFAULT, run_units
from moat.lib.path import P
from moat.link._test import Scaffold
from moat.util.time import patch_clock

from typing import Any, Self

CM_HEAT = P("app.heat.ha.heat")
PUMP_OUT = out_path("pump")
FLOW_REQ = P("app.heat.flow.request")
MODE = P("heat.s.pump.cmd.mode")
POWER = P("heat.s.pump.cmd.power")
PWM = P("heat.s.pump.pid")
PUMP_ERR = P("error.app.heat.pump")
WANTED = P("heat.s.pellets.power.cmd.auto")
FORCE = P("app.heat.force_start")


class WallClock:
    """
    Wall-clock time that follows trio's mock clock, and always advances.

    It never goes backwards, not even from one test to the next: the Link
    server's connection-rate check keeps state across the tests in a
    process. So it starts at the real time, or where the previous test's
    clock ended if that's later (a mock clock runs ahead). MoaT-Link also
    drops an update whose timestamp isn't newer than the stored one; with
    a mock clock, two updates can happen at the same instant, hence the
    nudge.
    """

    high: float = 0.0
    """The latest time handed out in this process."""

    def __init__(self) -> None:
        self.base = max(_real_time(), WallClock.high) + 1 - trio.current_time()

    def __call__(self) -> float:
        "the current wall-clock time"
        t = self.base + trio.current_time()
        WallClock.high = t if t > WallClock.high else WallClock.high + 1e-6
        return WallClock.high


class CheckedSim(SimLink):
    """
    The simulator, checking the safety invariants after every step:

    - the heat pump never runs while the water doesn't flow,
    - it doesn't trip,
    - the water pump runs while ``t_out - t_in`` exceeds 3 K.

    Brief violations (start-up, sensor lag) are allowed for a grace
    period.
    """

    flow_grace = 30
    pwm_grace = 120

    def __init__(self, *a: Any, **kw: Any) -> None:
        super().__init__(*a, **kw)
        self._no_flow: float | None = None
        self._no_pwm: float | None = None

    async def step(self) -> None:
        "advance, then check"
        await super().step()
        p = self.plant
        tr = p.truth()
        now = p.now
        assert p.hp.stage != "trip", f"t={now}: the heat pump tripped"
        if p.hp.stage == "run" and tr["r_flow"] < 0.5:
            self._no_flow = now if self._no_flow is None else self._no_flow
            assert now - self._no_flow <= self.flow_grace, f"t={now}: running without flow"
        else:
            self._no_flow = None
        if tr["t_out"] - tr["t_in"] > 3 and not p.inputs.pwm:
            self._no_pwm = now if self._no_pwm is None else self._no_pwm
            assert now - self._no_pwm <= self.pwm_grace, f"t={now}: hot heat pump, no water pump"
        else:
            self._no_pwm = None


class Heat:
    """
    All heat units and the simulator on one Scaffold, in simulated time.

    Args:
        cfg: The test configuration.
        scenario: The plant setup, as for `Scenario.from_dict`.
        config: Unit configuration items, by unit name.
        units: The units that `run_units` runs (with restarts).
        apart: Units that run on their own, so that a test can kill them
            (`kill`) and start them again (`start`).
    """

    def __init__(
        self,
        cfg: Any,
        scenario: dict[str, Any] | None = None,
        *,
        config: dict[str, Any] | None = None,
        units: tuple[str, ...] = DEFAULT,
        apart: tuple[str, ...] = (),
    ) -> None:
        self.cfg = cfg
        self.scenario = Scenario.from_dict(scenario or {})
        self.config = config or {}
        self.units = tuple(u for u in units if u not in apart)
        self.apart = apart
        self.scopes: dict[str, anyio.CancelScope] = {}
        self._stack = AsyncExitStack()
        self._clock = ExitStack()

    async def __aenter__(self) -> Self:
        self._clock.enter_context(patch_clock(time=WallClock()))
        st = self._stack
        self.sf = sf = await st.enter_async_context(Scaffold(self.cfg, use_servers=True))
        await st.enter_async_context(sf.server_(init={}))
        self.c = c = await st.enter_async_context(sf.client_())
        self.tg = await st.enter_async_context(anyio.create_task_group())
        for unit, item in self.config.items():
            await c.d_set(P("cfg.app.heat") / unit, item, retain=True)
        await c.d_set(CM_HEAT, True, retain=True)
        self.sim = CheckedSim(c, self.scenario)
        await self.tg.start(self.sim.run)
        if self.units:
            await self.tg.start(partial(run_units, sf.client_, self.units, retry=True))
        for u in self.apart:
            await self.start(u)
        return self

    async def __aexit__(self, *exc: object) -> bool | None:
        # Ending the test is not a pump failure: no emergency shutdown
        # against links that are going away.
        with patch.object(PumpUnit, "abort", _no_abort):
            self.tg.cancel_scope.cancel()
            try:
                return await self._stack.__aexit__(*exc)
            finally:
                self._clock.close()

    async def start(self, unit: str) -> None:
        "start a unit that runs on its own"
        self.scopes[unit] = await self.tg.start(self._run, unit)

    async def _run(self, unit: str, *, task_status: Any) -> None:
        with anyio.CancelScope() as sc:
            await run_units(
                self.sf.client_, [unit], retry=True, task_status=_Started(task_status, sc)
            )

    def kill(self, unit: str) -> None:
        "stop a unit that runs on its own"
        self.scopes.pop(unit).cancel()

    async def get(self, path: P) -> Any:
        "the current value of an item, or `None`"
        with suppress(KeyError):
            return await self.c.d_get(path)
        return None

    async def until(self, pred: Any, limit: float, step: float = 10) -> Any:
        "wait until ``await pred()`` is true-ish; return its value"
        with anyio.fail_after(limit):
            while True:
                if res := await pred():
                    return res
                await anyio.sleep(step)

    async def run(self) -> str | None:
        "the pump unit's state"
        return ((await self.get(PUMP_OUT)) or {}).get("run")

    async def running(self, limit: float = 600) -> None:
        "wait until the heat pump runs"
        await self.until(lambda: _is(self.run(), "run"), limit)


async def _no_abort(self: PumpUnit, exc: BaseException) -> None:
    "a pump unit's abort that doesn't shut the heat pump down"


class _Started:
    "a task status that hands back a cancel scope"

    def __init__(self, ts: Any, sc: anyio.CancelScope) -> None:
        self.ts = ts
        self.sc = sc

    def started(self, value: Any = None) -> None:  # noqa: ARG002
        "the unit runs"
        self.ts.started(self.sc)


async def _is(aw: Any, want: Any) -> bool:
    return (await aw) == want


async def _mode(aw: Any) -> str | None:
    return ((await aw) or {}).get("mode")


@pytest.mark.trio
async def test_warmup(cfg, jump) -> None:  # noqa: ARG001
    "all units and the simulator: the heat pump starts and reaches ``run``"
    async with Heat(cfg) as h:
        await h.running()


@pytest.mark.slow
@pytest.mark.trio
async def test_steady_run(cfg, jump) -> None:  # noqa: ARG001
    "steady sensor values are re-sent, so a long run isn't mistaken for dead sensors"
    async with Heat(cfg) as h:
        await h.running()
        await anyio.sleep(16 * 60)  # longer than the pump's stale timeout
        assert await h.run() in ("run", "ice")
        assert await h.get(PUMP_ERR) is None


@pytest.mark.slow
@pytest.mark.trio
async def test_error_shutdown(cfg, jump) -> None:  # noqa: ARG001
    "a critical heat-pump error: the pump unit stops with an emergency shutdown"
    async with Heat(cfg) as h:
        await h.running()
        await anyio.sleep(120)
        before = (await h.get(FLOW_REQ))["seq"]
        h.sim.plant.inject_error(":2", 123)
        err = await h.until(lambda: h.get(PUMP_ERR), 120)
        assert "PumpAbort" in repr(err)
        await h.until(lambda: _is(h.get(MODE), 0), 60)
        assert await h.get(POWER) == 0
        await h.until(lambda: _is(_mode(h.get(FLOW_REQ)), "off"), 300)
        # restarted, the unit doesn't start the heat pump while the error is there
        await anyio.sleep(300)
        assert await h.run() == "off"
        # its requests continue after the emergency shutdown's (moat-8hjx)
        assert (await h.get(FLOW_REQ))["seq"] > before + 2


@pytest.mark.slow
@pytest.mark.trio
async def test_stale_sensor(cfg, jump) -> None:  # noqa: ARG001
    "a sensor stops updating while the heat pump runs: emergency shutdown"
    async with Heat(cfg, config={"pump": {"stale": 120}}) as h:
        await h.running()
        await anyio.sleep(60)
        h.sim.plant.faults.stale.add("t_in")
        err = await h.until(lambda: h.get(PUMP_ERR), 300)
        assert "stale sensor" in repr(err)
        await h.until(lambda: _is(h.get(MODE), 0), 60)
        assert await h.get(POWER) == 0


@pytest.mark.slow
@pytest.mark.trio
async def test_flow_dead_during_emergency(cfg, jump) -> None:  # noqa: ARG001
    """
    Residual risk (HEAT.md §2.6): without the flow unit, nobody executes the
    shutdown's drain request. The water pump keeps its last PWM, which
    keeps the heat pump from overheating, but nobody stops it either.
    """
    async with Heat(cfg, apart=("flow",)) as h:
        await h.running()
        await anyio.sleep(120)
        pwm = await h.get(PWM)
        assert pwm
        h.kill("flow")
        await anyio.sleep(30)
        h.sim.plant.inject_error(":2", 123)
        await h.until(lambda: h.get(PUMP_ERR), 120)
        await h.until(lambda: _is(_mode(h.get(FLOW_REQ)), "off"), 600)
        assert await h.get(MODE) == 0
        assert await h.get(PWM) == pwm  # unchanged: nobody turns it off
        assert h.sim.plant.inputs.pwm == pwm


@pytest.mark.slow
@pytest.mark.trio
async def test_overrides(cfg, jump) -> None:  # noqa: ARG001
    "operator overrides take effect, then lapse and are deleted"
    async with Heat(cfg) as h:
        await h.running()
        # the heat pump forced off: it stops, the burner takes over
        await set_override(h.c, "wp", False, duration=300)
        await h.until(lambda: _in(h.run(), ("down", "off")), 60)
        await h.until(lambda: _is(h.get(WANTED), True), 60)
        # the burner forced off too: nothing runs
        await set_override(h.c, "pellet", False, duration=600)
        await h.until(lambda: _is(h.get(WANTED), False), 60)
        assert await h.run() == "off"
        # the heat pump's override lapses: deleted, the heat pump is back
        await h.until(lambda: _gone(h.get(OVR / "wp")), 300)
        await h.running(300)
        assert await h.get(WANTED) is False
        # the burner's lapses too
        await h.until(lambda: _gone(h.get(OVR / "pellet")), 400)


@pytest.mark.slow
@pytest.mark.trio
async def test_force_start(cfg, jump) -> None:  # noqa: ARG001
    "a warm buffer keeps the heat pump off, unless it is forced on once"
    warm = {"buffer": {"t_init": (65, 60)}, "weather": {"mean": 15, "amp": 1}}
    async with Heat(cfg, {"plant": warm}) as h:
        await anyio.sleep(120)
        assert await h.run() == "off"
        assert ((await h.get(PUMP_OUT)) or {}).get("reason") == "warm"
        await set_force_start(h.c)
        await h.until(lambda: _in(h.run(), ("wait_time", "wait_flow", "flow", "wait_power")), 60)
        await h.until(lambda: _gone(h.get(FORCE)), 60)


async def _in(aw: Any, want: tuple[str, ...]) -> bool:
    return (await aw) in want


async def _gone(aw: Any) -> bool:
    return (await aw) is None
