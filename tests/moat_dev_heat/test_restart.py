"""
End-to-end: the pump unit dies while the heat pump runs, without running
its own emergency shutdown (as after SIGKILL or an OOM kill), and is
restarted, without and with the watchdog (HEAT.md §3.8); also while the
original controller runs the heat pump (passthru).
"""

from __future__ import annotations

import anyio
import pytest

from moat.dev.heat.link import out_path
from moat.dev.heat.override import set_override
from moat.dev.heat.passthru import passthru
from moat.dev.heat.pump import PumpUnit
from moat.dev.heat.state import state_path
from moat.lib.path import P

from .test_integration import FLOW_REQ, MODE, POWER, PUMP_ERR, Heat, _is, _mode, _no_abort

from typing import Any

WATCHDOG_OUT = out_path("watchdog")
PASSTHRU = state_path("passthru")
REQUEST = P("app.heat.passthru.request")
RATE = P("heat.s.pump.rate.cmd")

pytestmark = [pytest.mark.slow, pytest.mark.trio]


async def _hard_kill(h: Heat, monkeypatch: Any) -> None:
    "kill the pump unit without its emergency shutdown"
    with monkeypatch.context() as m:
        m.setattr(PumpUnit, "abort", _no_abort)
        h.kill("pump")
        await anyio.sleep(1)


async def test_restart(cfg, jump, monkeypatch) -> None:  # noqa: ARG001
    "restarted quickly, the pump unit carries on from its saved state"
    async with Heat(cfg, apart=("pump",)) as h:
        await h.running()
        await anyio.sleep(300)
        await _hard_kill(h, monkeypatch)
        await anyio.sleep(10)
        assert await h.get(MODE) == 3  # the heat pump runs on, as it would
        await h.start("pump")
        await h.until(lambda: _is(h.run(), "run"), 60, step=1)
        assert await h.get(MODE) == 3
        assert await _mode(h.get(FLOW_REQ)) != "drain"
        await anyio.sleep(300)
        assert await h.run() in ("run", "ice")
        assert await h.get(PUMP_ERR) is None


async def test_watchdog(cfg, jump, monkeypatch) -> None:  # noqa: ARG001
    "the pump unit stays dead: the watchdog shuts the heat pump down"
    async with Heat(cfg, apart=("pump", "watchdog")) as h:
        await h.running()
        await anyio.sleep(300)
        await _hard_kill(h, monkeypatch)
        out = await h.until(lambda: _done(h.get(WATCHDOG_OUT)), 600, step=5)
        assert out["reason"].startswith("pump service gone")
        assert out["result"] in ("cooled", "timeout")
        assert await h.get(MODE) == 0
        assert await _mode(h.get(FLOW_REQ)) == "off"


async def _done(aw: Any) -> Any:
    o = await aw
    return o if o and o.get("status") == "done" else None


async def _solvis(h: Heat, *, task_status: Any) -> None:
    "the original controller runs the heat pump while bypassed, and stops for good afterwards"
    task_status.started()
    seen = False
    while True:
        if passthru(await h.get(PASSTHRU)):
            seen = True
            # forwarded through the Modbus bypass in reality
            await h.c.d_set(MODE, 3, retain=True)
            await h.c.d_set(POWER, 0.8, retain=True)
            await h.c.d_set(RATE, 0.6, retain=True)
        elif seen:
            return
        await anyio.sleep(5)


async def test_passthru_pump_dies(cfg, jump, monkeypatch) -> None:  # noqa: ARG001
    "the pump unit dies while the Solvis runs the heat pump: the watchdog ends the bypass"
    async with Heat(cfg, config={"passthru": {"compr": None}}, apart=("pump", "watchdog")) as h:
        await h.running()
        await set_override(h.c, "wp", False)
        await h.until(lambda: _is(h.run(), "off"), 600)
        await h.c.d_set(REQUEST, True, retain=True)
        await h.until(lambda: _bypassed(h.get(PASSTHRU)), 120)
        await set_override(h.c, "wp", None)
        await h.tg.start(_solvis, h)
        await h.until(lambda: _over(h.get(P("heat.s.pump.power")), 1.5), 600)
        await anyio.sleep(120)

        await _hard_kill(h, monkeypatch)
        # afterwards the pump unit's last output says "off": "idle", not "done"
        out = await h.until(lambda: _record(h.get(WATCHDOG_OUT)), 600, step=5)
        assert out["reason"] == "pump service gone while bypassed"
        assert out["result"] == "cooled"
        assert await h.get(PASSTHRU) == {"bypass": False, "switching": None}
        assert await h.get(REQUEST) is False
        assert await h.get(MODE) == 0
        assert await h.get(POWER) == 0
        assert await _mode(h.get(FLOW_REQ)) == "off"


async def _record(aw: Any) -> Any:
    o = await aw
    return o if o and "result" in o else None


async def _bypassed(aw: Any) -> bool:
    return passthru(await aw)


async def _over(aw: Any, limit: float) -> bool:
    return ((await aw) or 0) > limit
