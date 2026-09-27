"""
Tests for the plant simulator's MoaT-Link adapter and scenario files.
"""

from __future__ import annotations

import anyio
import pytest

from moat.util import yload
from moat.dev.heat.sim.link import SimLink
from moat.dev.heat.sim.paths import INPUT_PATHS, SENSOR_PATHS
from moat.dev.heat.sim.scenario import Event, Scenario

from typing import Any

TMO = 2


def test_scenario_parse():
    "scenario files: plant overrides, sorted events, bad input rejected"
    sc = Scenario.from_dict(
        yload(
            """\
seed: 3
plant: {weather: {mean: 2}}
events:
- {t: 20, stale: t_out}
- {t: 10, set: {path: !P heat.s.heat.temp.cmd, value: 38}}
"""
        )
    )
    assert sc.seed == 3
    assert sc.make_plant().cfg.weather.mean == 2
    assert [e.kind for e in sc.events] == ["set", "stale"]
    assert [e.kind for e in sc.due(15)] == ["set"]
    assert [e.kind for e in sc.events] == ["stale"]

    with pytest.raises(ValueError, match="one of"):
        Event.from_dict({"t": 1, "boom": 1})
    with pytest.raises(KeyError):
        Scenario.from_dict({"weather": {}})


async def _started(sim: SimLink, tg: anyio.abc.TaskGroup) -> None:
    "run the input readers and publish once, without the timed loop"
    await tg.start(sim.inputs.run)
    await sim.publish()
    await sim.link.i_sync()


@pytest.mark.anyio
async def test_publishes_sensors(link):
    "every sensor path is published, retained"
    async with anyio.create_task_group() as tg:
        await tg.start(SimLink(link, dt=10, scale=1000).run)
        await link.i_sync()
        for paths in SENSOR_PATHS.values():
            for p in paths:
                assert isinstance(await link.d_get(p), (int, float, bool)), p
        tg.cancel_scope.cancel()


@pytest.mark.anyio
async def test_reacts_to_commands(link):
    "a written command reaches the plant within one step"
    sim = SimLink(link)
    async with anyio.create_task_group() as tg:
        await _started(sim, tg)
        await link.d_set(INPUT_PATHS["pwm"], 0.8, retain=True)
        with anyio.fail_after(TMO):
            await sim.inputs.readers["pwm"].wait_value()
        await sim.step()
        assert sim.plant.inputs.pwm == 0.8
        tg.cancel_scope.cancel()


@pytest.mark.anyio
async def test_stale_sensor(link, monkeypatch):
    "a scenario fault makes a sensor stop updating; `set` writes an item"
    sc = Scenario.from_dict({
        "events": [
            {"t": 30, "stale": "tb_water"},
            {"t": 30, "set": {"path": INPUT_PATHS["heat_setpoint"], "value": 38}},
        ]
    })
    sim = SimLink(link, sc)
    path = SENSOR_PATHS["tb_water"][0]
    writes: list[Any] = []

    async def d_set(p, value=None, **kw):
        if p == path:
            writes.append(sim.plant.now)
        return await orig(p, value, **kw)

    orig = link.d_set
    monkeypatch.setattr(link, "d_set", d_set)
    async with anyio.create_task_group() as tg:
        await _started(sim, tg)
        for _ in range(30):
            await sim.step()
        tg.cancel_scope.cancel()

    assert writes
    assert max(writes) <= 40  # the stale fault starts in the step after t=30
    assert await link.d_get(INPUT_PATHS["heat_setpoint"]) == 38
    assert sim.plant.inputs.heat_setpoint == 38
