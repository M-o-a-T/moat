"""
Tests for ``moat dev heat run`` (the unit runner).
"""

from __future__ import annotations

import anyio
import pytest

from moat.dev.heat.link import ServiceMonitor
from moat.dev.heat.system.runner import DEFAULT, UNITS, run_units


def test_units() -> None:
    "every unit is known; the watchdog doesn't run by default"
    assert set(UNITS) == {
        "target",
        "heat_valve",
        "flow",
        "pump",
        "pellet",
        "selector",
        "errors",
        "frost",
        "watchdog",
    }
    assert "watchdog" not in DEFAULT
    assert set(DEFAULT) == set(UNITS) - {"watchdog"}


@pytest.mark.anyio
async def test_run(heat) -> None:
    "the runner starts units, each announced on its own client"
    mons = {n: ServiceMonitor(heat.link, "heat", n) for n in ("target", "frost")}
    async with anyio.create_task_group() as tg:
        for m in mons.values():
            await tg.start(m.run)
        await tg.start(run_units, heat.sf.client_, ["target", "frost"])
        with anyio.fail_after(2):
            for m in mons.values():
                while not m.alive:
                    await m.wait_changed()
        tg.cancel_scope.cancel()


@pytest.mark.anyio
async def test_unknown() -> None:
    "an unknown unit is an error"
    with pytest.raises(KeyError):
        await run_units(None, ["frobnicate"])  # ty:ignore[invalid-argument-type]


async def test_cli_help(capfd) -> None:
    "``moat dev heat run`` exists"
    from moat.src.test import run  # noqa: PLC0415

    # (not "moat dev heat --help": listing the commands imports the legacy
    # module, which messes with the global configuration)
    await run("dev", "heat", "run", "--help", do_stdout=False)
    assert "watchdog" in capfd.readouterr().out
