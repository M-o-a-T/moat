"""
Tests for the emergency shutdown (HEAT.md §2.6), on a MoaT-Link test server.
"""

from __future__ import annotations

import anyio
import platform
import pytest

from moat.dev.heat.config import EmergencyCfg
from moat.dev.heat.emergency import PUMP_SERVICE, emergency_shutdown
from moat.dev.heat.flow import FlowMode
from moat.link.exceptions import ServiceSupplanted

from typing import Any

pytestmark = pytest.mark.anyio

CFG = EmergencyCfg(timeout=1.0, max_sensor_age=0.5, total_timeout=5.0)


class Recorder:
    "collects the commands the procedure writes, in order"

    def __init__(self, link, cfg: EmergencyCfg) -> None:
        self.link = link
        self.paths = {
            cfg.power_path: "power",
            cfg.mode_path: "mode",
            cfg.flow_request: "flow",
        }
        self.seen: list[tuple[str, Any]] = []

    async def _watch(self, path, name, *, task_status) -> None:
        async with self.link.d_watch(path, state=False) as mon:
            task_status.started()
            async for v in mon:
                self.seen.append((name, v["mode"] if name == "flow" else v))

    async def start(self, tg) -> None:
        "start watching"
        for p, n in self.paths.items():
            await tg.start(self._watch, p, n)


async def _feed(link, cfg: EmergencyCfg, t_in: float, t_out: float) -> None:
    await link.d_set(cfg.sensor_in, t_in, retain=True)
    await link.d_set(cfg.sensor_out, t_out, retain=True)


async def _cool_later(link, cfg: EmergencyCfg, delay: float = 0.3) -> None:
    "hot first, then cooled down, with fresh values"
    await _feed(link, cfg, 30.0, 40.0)
    await anyio.sleep(delay)
    await _feed(link, cfg, 30.0, 31.0)


async def test_sequence_cooled(link):
    "commands in order; ends when fresh sensors show the heat exchanger cooled down"
    rec = Recorder(link, CFG)
    async with anyio.create_task_group() as tg:
        await rec.start(tg)
        tg.start_soon(_cool_later, link, CFG)
        with anyio.fail_after(3):
            res = await emergency_shutdown(link, CFG, from_pump=True)
        await anyio.sleep(0.2)
        tg.cancel_scope.cancel()
    assert res == "cooled"
    assert rec.seen == [
        ("power", 0),
        ("mode", CFG.mode_off),
        ("flow", FlowMode.DRAIN),
        ("flow", FlowMode.OFF),
    ]


async def test_seq_increments(link):
    "the flow requests continue the existing sequence numbers"
    await link.d_set(CFG.flow_request, {"mode": "temp", "temp": 45, "seq": 41}, retain=True)
    with anyio.fail_after(3):
        await emergency_shutdown(link, CFG, from_pump=True)
    await link.i_sync()
    assert (await link.d_get(CFG.flow_request))["seq"] == 43


async def test_timeout_without_sensors(link):
    "no sensor data: waits for the timeout, then still stops the water pump"
    t0 = anyio.current_time()
    with anyio.fail_after(3):
        res = await emergency_shutdown(link, CFG, from_pump=True)
    assert res == "timeout"
    assert anyio.current_time() - t0 >= CFG.timeout
    await link.i_sync()
    assert (await link.d_get(CFG.flow_request))["mode"] == FlowMode.OFF


async def test_stale_sensors_ignored(link):
    "cool but old sensor values don't end the wait"
    await _feed(link, CFG, 30.0, 31.0)
    await anyio.sleep(CFG.max_sensor_age + 0.2)
    with anyio.fail_after(3):
        res = await emergency_shutdown(link, CFG, from_pump=True)
    assert res == "timeout"


async def test_total_timeout(link):
    "total_timeout bounds a step that hangs"
    cfg = CFG.model_copy(update={"timeout": 30.0, "total_timeout": 0.5})
    t0 = anyio.current_time()
    with anyio.fail_after(3):
        res = await emergency_shutdown(link, cfg, from_pump=True)
    assert res == "total_timeout"
    assert anyio.current_time() - t0 < 1.5


async def _owner(heat_scaffold, *, task_status) -> None:
    "a stand-in for the pump unit, holding the pump service on its own client"
    async with (
        heat_scaffold.client_() as c,
        c.announcing(PUMP_SERVICE, host="heat") as srv,
    ):
        srv.set()
        task_status.started()
        await anyio.sleep_forever()


@pytest.mark.parametrize("other_host", [False, True])
async def test_supplant(heat_scaffold, link, monkeypatch, other_host: bool) -> None:
    "the procedure takes over the pump service; its owner gets ServiceSupplanted"
    if other_host:
        monkeypatch.setattr(platform, "node", lambda: "elsewhere")
    got: list[BaseException] = []
    done = anyio.Event()

    async def owner(*, task_status) -> None:
        try:
            await _owner(heat_scaffold, task_status=task_status)
        except* ServiceSupplanted as exc:
            got.extend(exc.exceptions)
        done.set()

    async with anyio.create_task_group() as tg:
        await tg.start(owner)
        await anyio.sleep(0.2)
        tg.start_soon(_cool_later, link, CFG, 0.1)
        with anyio.fail_after(4):
            res = await emergency_shutdown(link, CFG, from_pump=False)
        with anyio.fail_after(2):
            await done.wait()
        tg.cancel_scope.cancel()
    assert res == "cooled"
    assert len(got) == 1
