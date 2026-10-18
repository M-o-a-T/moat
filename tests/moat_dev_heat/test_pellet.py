"""
Tests for the pellet unit: state codes, ``t_pellet_on``, load branches,
temperature requests, selector edges, override, restart, closed loop
against the legacy ``pellet_handover`` trace, and the Link adapter
(HEAT.md §3.5).
"""

from __future__ import annotations

import pytest

from moat.util import NotGiven
from moat.dev.heat.config import make_config
from moat.dev.heat.link import out_path
from moat.dev.heat.pellet import Mode, PelletCfg, PelletCore, PelletState, PelletUnit, classify
from moat.dev.heat.pid import T_OFFSET
from moat.lib.path import P
from moat.util.time import patch_clock

from typing import Any

OUT = out_path("pellet")
LOAD = P("heat.s.pellets.load.goal.cmd")
TEMP = P("heat.s.pellets.temp.goal.cmd")
PATCH = P("heat.s.pellets.aux:1.goal")
DEM = {"t_nom": 50.0, "t_low": 51.0, "t_adj": 51.5, "source": "heat"}


def _cfg(item: Any = NotGiven) -> PelletCfg:
    return make_config("pellet", PelletCfg, item)


class Run:
    "steps a core, 10 s at a time, with a fake wall clock"

    def __init__(self, item: Any = NotGiven, pstate: PelletState | None = None, **inputs: Any):
        self.core = PelletCore(_cfg(item), pstate or PelletState(), 0)
        self.inputs: dict[str, Any] = {
            "state": 0,
            "tb_water": 50.0,
            "tb_heat": 50.0,
            "tb_mid": 45.0,
            "tb_low": 40.0,
            "t_pellet": 20.0,
            "force": None,
            "target": {"demand": DEM},
            "selector": None,
            "pump": {"run": "off"},
            "override": None,
        } | inputs
        self.now = 0.0

    def step(self, dt: float = 10, **inputs: Any) -> dict[Any, Any]:
        "advance and step; returns the outputs"
        self.now += dt
        self.inputs.update(inputs)
        with patch_clock(time=lambda: 1_000_000 + self.now):
            return self.core.step(dict(self.inputs), self.now).outputs

    @property
    def st(self) -> PelletState:
        "the core's state"
        return self.core.state


def test_classify():
    "every KWB state code: off, starting, running (4), or unchanged (2, cleaning)"
    off = {0, 1, 3, 5, 6, 7, 8, 9, *range(21, 36), *range(43, 60)}
    for c in range(60):
        if c == 2:
            for m in Mode:
                assert classify(c, m) == m
            continue
        want = Mode.RUNNING if c == 4 else Mode.OFF if c in off else Mode.STARTING
        assert classify(c) == want, c


@pytest.mark.parametrize("before", [0, 11, 4])
def test_cleaning(before: int):
    "code 2 (cleaning) keeps the mode, also across a restart"
    r = Run()
    r.step(state=before)
    mode = r.step()[OUT]["mode"]
    assert r.step(state=2)[OUT]["mode"] == mode
    r = Run(pstate=r.st)
    assert r.step(state=2)[OUT]["mode"] == mode


def test_t_pellet_on():
    "False while off; the start time while starting and running < t_min; then True"
    r = Run({"t_min": 100})
    out = r.step()
    assert (r.st.t_pellet_on, r.st.pellet_on, out[OUT]["mode"]) == (False, False, "off")
    r.step(state=11)
    t0 = r.st.t_pellet_on
    assert t0 == 1_000_020.0
    r.step()
    assert r.st.t_pellet_on == t0 + 10  # restarts while starting
    t0 = r.st.t_pellet_on
    r.step(state=4)
    assert (r.st.t_pellet_on, r.st.pellet_on) == (t0, True)
    for _ in range(10):
        r.step()
    assert r.st.t_pellet_on is True
    r.step(state=31)
    assert (r.st.t_pellet_on, r.st.pellet_on) == (False, False)


def test_running_without_start_is_settled():
    "legacy quirk: code 4 right after 'off' counts as settled at once"
    r = Run()
    r.step()
    r.step(state=4)
    assert r.st.t_pellet_on is True


def test_temp_and_patch():
    "starting: full load and a higher goal; running: tp_limit and the stop value"
    r = Run(tb_water=58.0, tb_heat=55.0)
    out = r.step(state=11)
    assert out[LOAD] == 1
    assert out[TEMP] == out[PATCH] == 63.0  # 5 + max(tb_water, tb_heat)
    r.inputs["tb_water"] = 30.0
    assert r.step()[TEMP] == 60  # at least temp_min

    out = r.step(state=4, tb_heat=52.0)
    assert out[PATCH] == 65
    assert out[TEMP] == 60  # max(60, t_adj + 2)
    out = r.step(tb_heat=41.0)  # far below t_low: request more
    assert out[TEMP] == pytest.approx(max(60, 51.5 + 2 + (51 - 41) * 0.4))


def test_load_branches():
    "F: forced; B: far below t_load; C: heat pump runs; -: PIDs"
    r = Run(state=4, tb_heat=35.0)  # t_load 54.5, more than 15 below
    r.step()
    assert (r.step()[LOAD], r.core._branch) == (1.0, "B")  # noqa: SLF001

    r.inputs["tb_heat"] = 53.0
    out = r.step(pump={"run": "run"})
    assert (out[LOAD], r.core._branch) == (1.0, "C")  # noqa: SLF001

    out = r.step(force=0.6)
    assert (out[LOAD], r.core._branch) == (0.6, "F")  # noqa: SLF001

    r.inputs["force"] = None
    loads = [r.step(pump={"run": "off"}, tb_heat=56.0)[LOAD] for _ in range(100)]
    assert r.core._branch == "-"  # noqa: SLF001
    assert min(loads) >= 0.3  # the PIDs' minimum
    assert loads[-1] < 0.6  # buffer above t_load: less than the forced load


def test_selector_edges():
    "switch-on presets the PIDs to full load; switch-off resets t_pellet_on and the load"
    r = Run(state=4, tb_heat=56.0, selector={"pellet": False})
    for _ in range(50):
        low = r.step()[LOAD]
    assert low < 0.9
    out = r.step(selector={"pellet": True})
    assert out[LOAD] == pytest.approx(1.0, abs=0.05)
    assert r.st.t_pellet_on is True

    r.step(selector={"pellet": False}, state=31)
    assert (r.st.t_pellet_on, r.st.load) == (False, 0)


def test_override():
    "override True switches on like the selector; False sets the load to 0"
    r = Run(state=4, tb_heat=56.0, selector={"pellet": False})
    for _ in range(50):
        r.step()
    out = r.step(override=True)
    assert out[LOAD] == pytest.approx(1.0, abs=0.05)
    out = r.step(override=False)
    assert (out[LOAD], out[OUT]["reason"]) == (0, "override")
    out = r.step(state=11)
    assert out[LOAD] == 0


def test_missing_input():
    "no state code or no demand: nothing written"
    r = Run(state=None)
    out = r.step()
    assert set(out) == {OUT}
    assert out[OUT]["reason"] == "missing: state"
    out = r.step(state=4, target={})
    assert out[OUT]["reason"] == "missing: demand"


def test_restart():
    "a restarted core keeps t_pellet_on and continues the load without a step"
    a = Run({"t_min": 1e6}, state=11)
    a.step()
    a.step(state=4, tb_heat=56.0)
    for _ in range(30):
        a.step()
    t_on = a.st.t_pellet_on
    assert isinstance(t_on, float)
    data = a.st.model_dump(context={T_OFFSET: 1000})
    st = PelletState.model_validate(data, context={T_OFFSET: 1000})
    assert st.t_pellet_on == t_on
    b = Run({"t_min": 1e6}, st, **a.inputs)
    b.now = a.now
    la, lb = a.step()[LOAD], b.step()[LOAD]
    assert lb == pytest.approx(la, abs=0.01)


def test_unit_inputs():
    "the adapter watches every input the core reads"
    u = PelletUnit.__new__(PelletUnit)
    u.link = None
    assert set(u.make_inputs(_cfg())) == set(Run().inputs)


# Link


@pytest.mark.anyio
async def test_unit(heat):
    "on MoaT-Link: the burner starts, runs and gets its load and temperature"
    await heat.feed(out_path("target"), {"demand": DEM})
    for k, v in (("water", 58.0), ("heat", 50.0), ("mid", 45.0), ("return", 40.0)):
        await heat.feed(P("heat.s.buffer.temp") / k, v)
    await heat.feed(P("heat.s.pellets.state"), 11)
    u = await heat.run_unit(PelletUnit)
    assert await heat.expect(TEMP, lambda v: v == 63.0) == 63.0
    assert await heat.expect(LOAD, lambda v: v == 1) == 1

    await heat.feed(P("heat.s.pellets.state"), 4)
    assert await heat.expect(PATCH, lambda v: v == 65) == 65
    out = await u.wait("out", lambda o: o is not None and o["mode"] == "running")
    assert out["pellet_on"]
    st = await u.wait("state", lambda s: s is not None and s["pellet_on"])
    assert st["t_pellet_on"] is not False
