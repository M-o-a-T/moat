"""
Tests for the errors unit (error aggregator).
"""

from __future__ import annotations

import pytest

from moat.dev.heat.config import make_config
from moat.dev.heat.errors import STALE, ErrorsCfg, ErrorsCore, ErrorsState, ErrorsUnit
from moat.dev.heat.link import out_path
from moat.dev.heat.sim import PlantCfg
from moat.dev.heat.sim.loop import ClosedLoop
from moat.dev.heat.sim.paths import ERRORS
from moat.lib.path import P
from moat.util.time import patch_clock

from typing import Any

OUT = out_path("errors")
UP = {"id": "x", "up": True}


class Run:
    "steps a core with a changing error feed, at a fake wall-clock time"

    def __init__(self, **cfg: Any) -> None:
        self.core = ErrorsCore(make_config("errors", ErrorsCfg, cfg or None), ErrorsState(), 0)
        self.inputs: dict[str, Any] = {"feed": {}, "override": None, "source": None}
        self.wall = 1000.0

    def step(self, **inputs: Any) -> dict[str, Any]:
        "advance by 10 s; `err_N=code` sets feed entry `:N`"
        self.wall += 10
        for k, v in inputs.items():
            if k.startswith("err_"):
                feed = dict(self.inputs["feed"])
                feed[P(f":{k[4:]}")] = v
                self.inputs["feed"] = feed
            else:
                self.inputs[k] = v
        with patch_clock(time=lambda: self.wall):
            return self.core.step(dict(self.inputs), self.wall - 1000).outputs[OUT]


def test_set_and_clear():
    "an error code shows up, and goes away when it is reset to 0"
    r = Run()
    out = r.step()
    assert out == {"errors": {}, "severity": "none", "since": 1010}
    out = r.step(err_3=1234)
    assert out == {"errors": {":3": 1234}, "severity": "critical", "since": 1020}
    out = r.step(err_4=77)
    assert out["errors"] == {":3": 1234, ":4": 77}
    assert out["since"] == 1020  # severity unchanged
    r.step(err_3=0)
    out = r.step(err_4=0)
    assert out == {"errors": {}, "severity": "none", "since": 1050}


def test_ignore():
    "the communication error and entry :1 are ignored by default; both are configurable"
    r = Run()
    out = r.step(err_2=30055, err_1=99)
    assert (out["errors"], out["severity"]) == ({}, "none")

    r = Run(ignore_codes=[5], ignore_paths=[])
    out = r.step(err_2=30055, err_1=99, err_3=5)
    assert out["errors"] == {":2": 30055, ":1": 99}


def test_severity():
    "per-code severity; the worst one wins"
    r = Run(severity={10: "warning", 11: "none"})
    assert r.step(err_2=11)["severity"] == "none"
    out = r.step(err_3=10)
    assert (out["severity"], out["since"]) == ("warning", 1020)
    assert r.step(err_4=12)["severity"] == "critical"
    out = r.step(err_4=0)
    assert (out["severity"], out["since"]) == ("warning", 1040)


def test_stale_feed():
    "when the feed's writer is not announced, a synthetic critical error appears"
    src = P("run.host.s-bed.modbus.heat")
    r = Run(source=src)
    out = r.step()
    assert (out["errors"], out["severity"]) == ({STALE: STALE}, "critical")
    out = r.step(source=UP)
    assert (out["errors"], out["severity"]) == ({}, "none")
    out = r.step(source={"id": "x", "up": False})
    assert out["errors"] == {STALE: STALE}

    # without a configured source there is nothing to check
    assert Run().step()["errors"] == {}


def test_override():
    "an operator can inject errors"
    r = Run(severity={3: "warning"})
    out = r.step(override={"test": 3})
    assert (out["errors"], out["severity"]) == ({"test": 3}, "warning")
    out = r.step(err_2=4)
    assert out["errors"] == {"test": 3, ":2": 4}
    assert r.step(override=None, err_2=0)["errors"] == {}


def test_restart_keeps_since():
    "a restarted core reports the time of the last severity change, not its start"
    r = Run()
    r.step(err_2=4)
    st = ErrorsState.model_validate(r.core.state.model_dump())
    r2 = Run()
    r2.core.state = st
    r2.wall = r.wall
    r2.inputs = r.inputs
    assert r2.step()["since"] == 1010


def test_closed_loop():
    "against the simulated plant, an injected heat-pump error is reported and cleared"
    loop = ClosedLoop(cfg=PlantCfg(), seed=1)
    loop.set(ERRORS / "old", 5)  # present before the unit starts
    loop.add_unit(ErrorsUnit)
    loop.run(20, 10)
    assert loop.get(OUT)["errors"] == {"old": 5}

    loop.plant.inject_error("7", 42)
    loop.run(20, 10)
    assert loop.get(OUT)["errors"] == {"old": 5, "7": 42}
    loop.set(ERRORS / "old", None)
    loop.plant.clear_error("7")
    loop.run(20, 10)
    out = loop.get(OUT)
    assert (out["errors"], out["severity"]) == ({}, "none")


@pytest.mark.anyio
async def test_unit(heat):
    "on MoaT-Link: the error subtree is watched, including existing entries"
    await heat.feed(P("heat.s.pump.err:5"), 1234)
    await heat.seed_config("errors", {"source": P("run.host.x.feed")})
    u = await heat.run_unit(ErrorsUnit)
    out = await u.wait("out", lambda o: o is not None)
    assert out["errors"] == {":5": 1234, STALE: STALE}

    await heat.feed(P("run.host.x.feed"), UP)
    await heat.feed(P("heat.s.pump.err:6"), 30055)
    await heat.feed(P("heat.s.pump.err:7"), 99)
    out = await u.wait("out", lambda o: ":7" in o["errors"])
    assert out["errors"] == {":5": 1234, ":7": 99}

    await heat.feed(P("heat.s.pump.err:5"), 0)
    await heat.feed(P("heat.s.pump.err:7"), 0)
    out = await u.wait("out", lambda o: not o["errors"])
    assert out["severity"] == "none"
    st = await u.wait("state", lambda s: s is not None and s["severity"] == "none")
    assert st["since"] == out["since"]
