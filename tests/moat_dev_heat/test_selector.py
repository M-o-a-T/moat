"""
Tests for the selector unit (HEAT.md §3.6).
"""

from __future__ import annotations

import pytest

from moat.util import NotGiven
from moat.dev.heat.config import make_config
from moat.dev.heat.link import out_path
from moat.dev.heat.selector import (
    PELLET,
    WP,
    Phase,
    SelectorCfg,
    SelectorCore,
    SelectorState,
    SelectorUnit,
)
from moat.lib.path import P

from typing import Any

OUT = out_path("selector")
WANTED = P("heat.s.pellets.power.cmd.auto")
DEM = {"t_nom": 50.0, "t_low": 52.0, "t_adj": 52.0, "t_set_on": 50.0, "t_set_off": 50.0}


def _cfg(item: Any = NotGiven) -> SelectorCfg:
    return make_config("selector", SelectorCfg, item)


class Run:
    "a selector core with inputs that can be changed step by step"

    def __init__(self, item: Any = NotGiven, **kw: Any) -> None:
        self.core = SelectorCore(_cfg(item), SelectorState(**kw.pop("state", {})), 0)
        self.now = 0.0
        self.inputs: dict[str, Any] = {
            "m_air": 5.0,
            "m_air_pred": 5.0,
            "pellet_state": 0,
            "tb_water": 55.0,
            "tb_heat": 55.0,
            "tb_low": 40.0,
            "cm_heat": True,
            "target": {"t_ext": 5.0, "demand": DEM},
            "pump": {"run": "off"},
            "pellet": {"t_pellet_on": False, "mode": "off", "hot": False},
            "errors": {"errors": {}},
            "override_wp": None,
            "override_pellet": None,
        }
        self.inputs.update(kw)
        self.out: dict[str, Any] = {}
        self.res: Any = None

    def step(self, dt: float = 10, **kw: Any) -> dict[str, Any]:
        "advance by ``dt`` seconds, with changed inputs"
        self.now += dt
        self.inputs.update(kw)
        self.res = self.core.step(self.inputs, self.now)
        self.out = self.res.outputs[OUT]
        assert self.res.outputs[WANTED] is self.out[PELLET]
        return self.out

    def until(self, pred, **kw: Any) -> float:
        "step until ``pred(out)``; return the time it took"
        t0 = self.now
        self.inputs.update(kw)
        while not pred(self.step()):
            assert self.now - t0 < 20000, self.out
        return self.now - t0

    @property
    def state(self) -> tuple[str | None, str, bool, bool]:
        "primary, phase, wp, pellet"
        o = self.out
        return o["primary"], o["phase"], o[WP], o[PELLET]


COLD = {"m_air": -3.0, "m_air_pred": -5.0, "tb_water": 45.0, "tb_heat": 45.0}
WARM = {"m_air": 3.0, "m_air_pred": 2.0, "tb_heat": 55.0, "target": {"t_ext": 3.0, "demand": DEM}}


def _pellet(mode: str = "running", hot: bool = False, t_on: Any = True) -> dict[str, Any]:
    return {"t_pellet_on": t_on, "mode": mode, "hot": hot, "pellet_on": mode == "running"}


def _on_pellet(r: Run) -> None:
    "bring a Run to steady pellet operation"
    r.until(lambda o: o["phase"] == Phase.WP_TO_PELLET, **COLD)
    r.until(lambda o: o["phase"] == Phase.STEADY, pellet=_pellet(hot=True), pellet_state=4)
    assert r.state == (PELLET, "steady", False, True)


# primary choice


def test_start() -> None:
    "warm: the heat pump alone"
    r = Run()
    assert r.step() == {
        WP: True,
        PELLET: False,
        "primary": WP,
        "phase": "steady",
        "reason": "start",
        "failed": [],
    }


@pytest.mark.parametrize(
    ("kw", "switch"),
    [
        ({}, True),
        ({"m_air": 1.5}, False),  # not cold now
        ({"m_air": 0.5, "m_air_pred": 0.4}, False),  # within the hysteresis ...
        ({"m_air": 0.5, "m_air_pred": 0.3}, True),  # ... and below it
        ({"tb_water": 50.0, "tb_heat": 50.0}, False),  # buffer at t_nom
        ({"tb_water": 50.0}, True),  # heating on: the colder of both counts
        ({"tb_water": 50.0, "cm_heat": False}, False),  # heating off: water only
        ({"pellet_state": 4}, False),  # the burner isn't idle
        ({"m_air": None}, False),  # missing input: latch
        ({"target": None}, False),
    ],
)
def test_to_pellet_conditions(kw: dict[str, Any], switch: bool) -> None:
    "the legacy switch-on conditions"
    r = Run(**{**COLD, "m_air_pred": 0.0, **kw})
    for _ in range(20):
        r.step()
    assert (r.out["primary"] == PELLET) is switch


@pytest.mark.parametrize(
    ("kw", "switch"),
    [
        ({}, True),
        ({"m_air": 0.9}, False),
        ({"m_air_pred": 0.6}, False),  # hysteresis
        ({"m_air_pred": 0.7}, True),
        ({"tb_heat": 52.0}, False),  # not above t_low
        ({"target": {"t_ext": -1.0, "demand": DEM}}, False),  # avg_off
        ({"pellet": _pellet(t_on=12345.0)}, False),  # the burner is starting
    ],
)
def test_to_wp_conditions(kw: dict[str, Any], switch: bool) -> None:
    "the legacy switch-off conditions"
    r = Run()
    _on_pellet(r)
    r.inputs.update({**WARM, "m_air_pred": 0.7, **kw})
    for _ in range(20):
        r.step()
    assert (r.out["primary"] == WP) is switch


def test_debounce() -> None:
    "a change must be called for `debounce` seconds without interruption"
    r = Run()
    r.step(**COLD)
    r.step(dt=100)
    r.step(m_air=5.0)  # interrupted
    r.step(m_air=-3.0)
    r.step(dt=100)
    assert r.out["primary"] == WP
    r.step(dt=30)
    assert r.out["primary"] == PELLET


# handovers


def test_wp_to_pellet() -> None:
    "the heat pump runs until the burner is hot"
    r = Run()
    r.until(lambda o: o["primary"] == PELLET, **COLD)
    assert r.state == (PELLET, "wp_to_pellet", True, True)
    r.step(dt=600, pellet=_pellet("starting", t_on=1.0), pellet_state=11)
    assert r.state == (PELLET, "wp_to_pellet", True, True)
    r.step(dt=600, pellet=_pellet(t_on=2.0), pellet_state=4)
    assert r.state == (PELLET, "wp_to_pellet", True, True)
    r.step(pellet=_pellet(hot=True, t_on=2.0))
    assert r.state == (PELLET, "steady", False, True)
    assert r.out["reason"] == "burner hot"
    assert r.res.save_now


def test_pellet_to_wp() -> None:
    "the burner runs until the heat pump has run for `stable` seconds"
    r = Run()
    _on_pellet(r)
    r.until(lambda o: o["primary"] == WP, **WARM)
    assert r.state == (WP, "pellet_to_wp", True, True)
    r.step(dt=60, pump={"run": "temp"})
    r.step(dt=60, pump={"run": "run"})
    r.step(dt=300, pump={"run": "run"})
    r.step(dt=200, pump={"run": "down"})  # not stable: starts again
    r.step(dt=10, pump={"run": "run"})
    r.step(dt=590)
    assert r.state == (WP, "pellet_to_wp", True, True)
    r.step(dt=20)
    assert r.state == (WP, "steady", True, False)
    assert r.out["reason"] == "heat pump runs"


def test_pellet_to_wp_idle() -> None:
    "a heat pump that isn't needed releases the burner, too"
    r = Run()
    _on_pellet(r)
    r.until(lambda o: o["primary"] == WP, **WARM)
    t = r.until(lambda o: o["phase"] == "steady", pump={"run": "off"})
    assert t == pytest.approx(1800, abs=20)
    assert r.out["reason"] == "heat pump idle"


# fallback


def test_pellet_does_not_start() -> None:
    "the burner doesn't run in time: back to the heat pump, with a reason"
    r = Run()
    r.until(lambda o: o["primary"] == PELLET, **COLD)
    t = r.until(lambda o: o["primary"] == WP, pellet=_pellet("starting", t_on=1.0))
    assert t == pytest.approx(1800, abs=20)
    assert r.state == (WP, "steady", True, False)
    assert r.out["reason"] == "pellet failed: burner doesn't run"
    assert r.out["failed"] == [PELLET]
    # it's still cold, but the burner isn't tried again for a while ...
    r.step(dt=600)
    r.step(dt=130)
    assert r.out["primary"] == WP
    assert r.out["reason"] == "pellet failed recently"
    # ... until `retry` has passed
    r.until(lambda o: o["primary"] == PELLET)
    assert r.out["failed"] == []


def test_pellet_not_hot() -> None:
    "the burner runs but doesn't get hot"
    r = Run()
    r.until(lambda o: o["primary"] == PELLET, **COLD)
    t = r.until(lambda o: o["primary"] == WP, pellet=_pellet(), pellet_state=4)
    assert t == pytest.approx(3600, abs=20)
    assert r.out["reason"] == "pellet failed: burner not hot in time"


def test_pellet_fault_code() -> None:
    "a configured fault code fails the burner at once, also in steady state"
    r = Run({"fail_codes": [99]})
    _on_pellet(r)
    r.step(pellet_state=99)
    assert r.state == (WP, "steady", True, False)
    assert r.out["reason"] == "pellet failed: burner fault 99"


def test_pellet_steady_pause() -> None:
    "a burner pausing with a warm buffer is fine; not running while it's cold isn't"
    r = Run()
    _on_pellet(r)
    r.step(dt=5000, pellet=_pellet("off"), tb_heat=55.0)
    r.step(dt=5000)
    assert r.state == (PELLET, "steady", False, True)
    t = r.until(lambda o: o["primary"] == WP, tb_heat=45.0)
    assert t == pytest.approx(1800, abs=20)


def test_wp_error_during_handover() -> None:
    "heat-pump errors while the burner comes: the burner stays"
    r = Run()
    r.until(lambda o: o["primary"] == PELLET, **COLD)
    r.step(errors={"errors": {":2": 123}})
    assert r.state == (PELLET, "wp_to_pellet", True, True)
    r.step(pellet=_pellet(hot=True))
    assert r.state == (PELLET, "steady", False, True)


def test_wp_error_pellet_to_wp() -> None:
    "heat-pump errors while it should take over: the burner stays"
    r = Run()
    _on_pellet(r)
    r.until(lambda o: o["primary"] == WP, **WARM)
    r.step(errors={"errors": {":2": 123}})
    assert r.state == (PELLET, "steady", False, True)
    assert r.out["reason"] == "wp failed: heat pump errors"


def test_wp_error_steady() -> None:
    "heat-pump errors: fall back to the burner, even when it's warm"
    r = Run()
    r.step(errors={"errors": {":2": 123}})
    assert r.state == (PELLET, "steady", False, True)
    r.step(dt=3000, errors={"errors": {}})
    assert r.out["primary"] == PELLET  # conditions for WP not met: buffer is warm etc.


# overrides


@pytest.mark.parametrize(
    ("ov_wp", "ov_pellet", "want"),
    [
        (None, None, (WP, "steady", True, False)),
        (True, None, (WP, "steady", True, False)),
        (None, True, (WP, "steady", True, True)),
        (True, True, (WP, "steady", True, True)),
        (False, None, (PELLET, "wp_to_pellet", False, True)),
        (False, True, (PELLET, "wp_to_pellet", False, True)),
        (None, False, (WP, "steady", True, False)),
        (True, False, (WP, "steady", True, False)),
        (False, False, (None, "steady", False, False)),
    ],
)
def test_override(ov_wp: Any, ov_pellet: Any, want: tuple[Any, ...]) -> None:
    "overrides force sources on or off"
    r = Run(override_wp=ov_wp, override_pellet=ov_pellet)
    r.step()
    assert r.state == want
    if want[0] is None:
        assert r.out["reason"] == "both sources off (override)"


def test_override_no_fallback() -> None:
    "a source forced off is never the fallback"
    r = Run(override_pellet=False)
    r.step(errors={"errors": {":2": 123}})
    assert r.state == (WP, "steady", True, False)
    r = Run(override_wp=False)
    r.step()
    r.step(pellet=_pellet(hot=True))
    assert r.state == (PELLET, "steady", False, True)
    r.step(dt=5000, pellet_state=99, tb_heat=45.0, pellet=_pellet("off"))
    r.step(dt=5000)
    assert r.state == (PELLET, "steady", False, True)


def test_override_cold_keeps_pellet() -> None:
    "forcing the burner off while it's primary hands over to the heat pump"
    r = Run()
    _on_pellet(r)
    r.step(override_pellet=False)
    assert r.state == (WP, "pellet_to_wp", True, False)
    r.step(override_pellet=None)
    # it's still cold, but the handover has started
    assert r.out["primary"] == WP


def test_override_released() -> None:
    "after both were off, the heat pump comes back"
    r = Run(override_wp=False, override_pellet=False)
    r.step()
    r.step(override_wp=None, override_pellet=None)
    assert r.state == (WP, "steady", True, False)


def test_restart() -> None:
    "the state survives a restart; failure latches restart their timer"
    st = SelectorState(primary=PELLET, phase=Phase.STEADY, failed={WP: -99999.0})
    r = Run(state=st.model_dump())
    r.step()
    assert r.state == (PELLET, "steady", False, True)
    assert r.out["failed"] == [WP]


@pytest.mark.anyio
async def test_unit(heat) -> None:
    "the adapter: cold weather requests the burner after the debounce time"
    await heat.seed_config("selector", {"debounce": 0.3})
    await heat.feed(P("app.heat.ha.t_air"), -3.0)
    await heat.feed(P("temp.min.forecast:6"), -5.0)
    await heat.feed(P("heat.s.pellets.state"), 0)
    await heat.feed(P("heat.s.buffer.temp.water"), 45.0)
    await heat.feed(P("heat.s.buffer.temp.heat"), 45.0)
    await heat.feed(P("app.heat.ha.heat"), True)
    await heat.feed(out_path("target"), {"t_ext": -3.0, "demand": DEM})
    u = await heat.run_unit(SelectorUnit)
    o = await u.wait("out", lambda o: o is not None and o["primary"] == PELLET)
    assert o[WP]
    assert o[PELLET]
    await heat.expect(WANTED, lambda v: v is True)
    await u.wait("state", lambda s: s is not None and s["primary"] == PELLET)
