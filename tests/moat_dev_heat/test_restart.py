"""
End-to-end: the pump unit dies while the heat pump runs, without running
its own emergency shutdown (as after SIGKILL or an OOM kill), and is
restarted, without and with the watchdog (HEAT.md §3.8).
"""

from __future__ import annotations

import anyio
import pytest

from moat.dev.heat.link import out_path
from moat.dev.heat.pump import PumpUnit

from .test_integration import FLOW_REQ, MODE, PUMP_ERR, Heat, _is, _mode, _no_abort

from typing import Any

WATCHDOG_OUT = out_path("watchdog")

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
