"""
Tests for the flow unit (water-pump PWM).
"""

from __future__ import annotations

import anyio
import pytest

from moat.dev.heat.config import make_config
from moat.dev.heat.flow import FlowCfg, FlowCore, FlowRequest, FlowState, FlowUnit
from moat.dev.heat.link import out_path, service_path
from moat.dev.heat.pid import T_OFFSET, PIDState
from moat.dev.heat.sim import PlantCfg
from moat.dev.heat.sim.loop import ClosedLoop
from moat.dev.heat.sim.paths import INPUT_PATHS, SENSOR_PATHS
from moat.lib.path import P

from typing import Any

OUT = P("heat.s.pump.pid")
UP = {"id": "x", "up": True}


def _core(**cfg: Any) -> FlowCore:
    return FlowCore(make_config("flow", FlowCfg, cfg or None), FlowState(), now=0)


def _req(seq: int = 1, **kw: Any) -> dict[str, Any]:
    return FlowRequest(seq=seq, **kw).to_link()


class Run:
    "steps a core with changing sensor values"

    def __init__(self, core: FlowCore, **inputs: Any) -> None:
        self.core = core
        self.inputs = {
            "request": None,
            "override": None,
            "r_flow": 0.0,
            "t_out": 30.0,
            "t_in": 28.0,
            "pump": UP,
        } | inputs
        self.now = 0.0
        self.n = 0

    def step(self, dt: float = 10, jitter: bool = True, **inputs: Any) -> tuple[float, dict]:
        "advance, optionally nudging the sensors so they don't look stale"
        self.now += dt
        self.n += 1
        self.inputs.update(inputs)
        if jitter:
            for k in ("r_flow", "t_out"):
                if k not in inputs and self.inputs[k] is not None:
                    self.inputs[k] += 0.001 if self.n % 2 else -0.001
        res = self.core.step(dict(self.inputs), self.now)
        return res.outputs[OUT], res.outputs[out_path("flow")]


def test_off_and_fixed():
    "off is 0 at once; fixed is the requested PWM"
    r = Run(_core())
    pwm, out = r.step(request=_req(mode="fixed", pwm=0.3))
    assert (pwm, out["mode"], out["request_seq"]) == (0.3, "fixed", 1)
    r.step(request=_req(2, mode="rate", rate=15), r_flow=5.0)
    pwm, out = r.step(request=_req(3, mode="off"))
    assert (pwm, out["mode"]) == (0.0, "off")


def test_rate_bounded():
    "the flow PID raises the PWM while the flow is too low, within its limits"
    r = Run(_core(), r_flow=2.0)
    pwms = [r.step(request=_req(mode="rate", rate=15))[0]]
    pwms += [r.step()[0] for _ in range(200)]
    assert pwms == sorted(pwms)
    assert pwms[0] >= 0.25
    assert pwms[-1] == pytest.approx(0.95)

    r = Run(_core(), r_flow=40.0)
    pwms = [r.step(request=_req(mode="rate", rate=15))[0] for _ in range(200)]
    assert min(pwms) == pytest.approx(0.25)


def test_preload():
    "a preloaded request starts at the given PWM"
    r = Run(_core(), r_flow=6.0)
    pwm, _ = r.step(request=_req(mode="rate", rate=6, pwm=0.4, preload=True))
    assert pwm == pytest.approx(0.4, abs=0.01)


def test_rate_temp_min():
    "rate_temp takes the larger PID output and honours min_pwm (de-icing)"
    r = Run(_core(), r_flow=40.0, t_out=20.0)
    pwm, out = r.step(request=_req(mode="rate_temp", rate=15, temp=45, min_pwm=0.4))
    assert out["mode"] == "rate_temp"
    assert pwm == pytest.approx(0.4)


def test_temp_over_max():
    "outflow above max_max: full speed"
    r = Run(_core(), t_out=50.0)
    r.step(request=_req(mode="temp", temp=45))
    pwm, _ = r.step(t_out=62.0)
    assert pwm == 1.0
    pwm, _ = r.step(t_out=40.0)
    assert pwm < 1.0


def test_stale_sensor():
    "a stale flow sensor: hold the PWM for `freeze`, then `safe_pwm`"
    r = Run(_core(max_age=60, freeze=60, safe_pwm=0.5), r_flow=2.0)
    held, out = r.step(request=_req(mode="rate", rate=15))
    while out["mode"] == "rate":
        last = held
        held, out = r.step(jitter=False)
        assert r.now <= 70
    assert (held, out["mode"]) == (last, "freeze")
    while out["mode"] == "freeze":
        pwm, out = r.step(jitter=False)
        assert pwm in (held, 0.5)
        assert r.now <= 140
    assert (pwm, out["mode"]) == (0.5, "safe")
    pwm, out = r.step(r_flow=3.0)
    assert out["mode"] == "rate"


def test_stale_request():
    "an old request without a live pump unit: safe_pwm while hot, then 0"
    r = Run(_core(request_max_age=100, stop_delta=3), t_out=40.0, t_in=30.0)
    r.step(request=_req(mode="rate", rate=15))
    for _ in range(12):
        _, out = r.step()
    assert out["mode"] == "rate"  # the pump unit is alive

    pwm, out = r.step(pump=None)
    assert (pwm, out["mode"]) == (0.5, "fallback")
    pwm, out = r.step(t_out=32.0)
    assert (pwm, out["mode"]) == (0.0, "idle")
    pwm, out = r.step(t_out=40.0)
    assert pwm == 0.0  # stays off until a new request

    pwm, out = r.step(request=_req(2, mode="fixed", pwm=0.3))
    assert pwm == 0.3


def test_override():
    "an operator override wins"
    r = Run(_core())
    r.step(request=_req(mode="fixed", pwm=0.3))
    pwm, out = r.step(override=0.7)
    assert (pwm, out["mode"]) == (0.7, "override")
    pwm, _ = r.step(override=None)
    assert pwm == 0.3


def test_idle_pid_does_not_integrate():
    "a PID that isn't used keeps up with the time"
    r = Run(_core(), r_flow=5.0)
    r.step(request=_req(mode="rate", rate=15))
    i = r.core.state.flow.i
    r.step(request=_req(2, mode="off"))
    for _ in range(100):
        r.step()
    assert r.core.state.flow.t == r.now
    r.step(request=_req(3, mode="rate", rate=15))
    assert r.core.state.flow.i - i < 0.1  # one normal step, not 1000 s worth


def test_restart_no_step():
    "a restarted core continues where the old one left off"
    cfg = make_config("flow", FlowCfg)
    a = Run(FlowCore(cfg, FlowState(), 0), r_flow=5.0)
    a.step(request=_req(mode="rate", rate=15))
    for _ in range(20):
        a.step()
    data = a.core.state.model_dump(context={T_OFFSET: 1000})
    st = FlowState.model_validate(data, context={T_OFFSET: 1000})
    b = Run(FlowCore(cfg, st, a.now), r_flow=a.inputs["r_flow"])
    b.now, b.n = a.now, a.n
    pa, _ = a.step()
    pb, _ = b.step(request=a.inputs["request"])
    assert pb == pytest.approx(pa)
    assert isinstance(st.flow, PIDState)


def test_closed_loop_rate():
    "against the simulated plant, the flow settles at the requested rate"
    loop = ClosedLoop(cfg=PlantCfg(), seed=2)
    loop.add_unit(FlowUnit)
    loop.set(service_path("heat", "pump"), UP)
    req = P("app.heat.flow.request")
    loop.set(req, _req(mode="rate", rate=15))
    loop.run(1800, 10)
    out = loop.get(out_path("flow"))
    assert out["mode"] == "rate"
    assert out["stable"]
    assert loop.get(SENSOR_PATHS["r_flow"][0]) == pytest.approx(15, abs=1)
    assert loop.get(INPUT_PATHS["pwm"]) == out["pwm"]


@pytest.mark.anyio
async def test_unit(heat):
    "on MoaT-Link: request → PWM; a restart resumes without a step"
    await heat.feed(P("heat.s.pump.flow"), 5.0)
    await heat.feed(P("app.heat.flow.request"), _req(mode="fixed", pwm=0.3))
    u = await heat.run_unit(FlowUnit)
    assert await heat.expect(OUT, lambda v: v == 0.3) == 0.3

    await heat.feed(
        P("app.heat.flow.request"), _req(2, mode="rate", rate=15, pwm=0.4, preload=True)
    )
    await u.wait("state", lambda s: s is not None and s["seq"] == 2)
    pwm = await heat.expect(OUT, lambda v: v is not None and v > 0.35)
    await u.wait("state", lambda s: s["pwm"] == pwm)
    u.cancel()

    u2 = await heat.run_unit(FlowUnit)
    await u2.wait("out", lambda o: o is not None and o["request_seq"] == 2)
    with anyio.fail_after(2):
        v = await heat.expect(OUT, lambda v: v is not None)
    assert v == pytest.approx(pwm, abs=0.02)


def test_stale_by_age():
    "with ages (from the adapter), an unchanged value is fresh while it keeps being updated"
    r = Run(_core(max_age=60, freeze=60, safe_pwm=0.5), r_flow=2.0)
    _, out = r.step(request=_req(mode="rate", rate=15), _age={"r_flow": 0})
    for _ in range(20):
        _, out = r.step(jitter=False, _age={"r_flow": 5})
        assert out["mode"] == "rate"
    _, out = r.step(jitter=False, _age={"r_flow": 61})
    assert out["mode"] == "freeze"
