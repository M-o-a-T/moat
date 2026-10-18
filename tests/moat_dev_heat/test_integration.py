"""
End-to-end scenarios: all heat units and the plant simulator on MoaT-Link
(HEAT.md §5.1, layer 3), in simulated time.
"""

from __future__ import annotations

import anyio
import pytest
from functools import partial
from time import time as _real_time

import trio

from moat.dev.heat.link import out_path
from moat.dev.heat.sim.link import SimLink
from moat.dev.heat.sim.scenario import Scenario
from moat.dev.heat.system.runner import DEFAULT, run_units
from moat.lib.path import P
from moat.link._test import Scaffold
from moat.util.time import patch_clock

CM_HEAT = P("app.heat.ha.heat")
PUMP_OUT = out_path("pump")


class WallClock:
    """
    Wall-clock time that follows trio's mock clock, and always advances.

    It starts at the real time: the Link server's connection-rate check
    keeps state across tests in a process, and breaks if time goes
    backwards. MoaT-Link also drops an update whose timestamp isn't newer
    than the stored one; with a mock clock, two updates can happen at the
    same instant, hence the nudge.
    """

    def __init__(self) -> None:
        self.base = _real_time() - trio.current_time()
        self.last = 0.0

    def __call__(self) -> float:
        "the current wall-clock time"
        t = self.base + trio.current_time()
        self.last = t if t > self.last else self.last + 1e-6
        return self.last


@pytest.mark.trio
async def test_warmup(cfg, autojump_clock) -> None:
    "all units and the simulator: the heat pump starts and reaches ``run``"
    autojump_clock.autojump_threshold = 0.005
    with patch_clock(time=WallClock()):
        async with (
            Scaffold(cfg, use_servers=True) as sf,
            sf.server_(init={}),
            sf.client_() as c,
            anyio.create_task_group() as tg,
        ):
            await c.d_set(CM_HEAT, True, retain=True)
            await tg.start(SimLink(c, Scenario.from_dict({})).run)
            await tg.start(partial(run_units, sf.client_, DEFAULT))
            with anyio.fail_after(3600):
                while True:
                    try:
                        if (await c.d_get(PUMP_OUT))["run"] == "run":
                            break
                    except KeyError:
                        pass
                    await anyio.sleep(10)
            tg.cancel_scope.cancel()
