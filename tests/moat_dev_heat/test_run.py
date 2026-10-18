"""
Tests for ``moat dev heat run`` (the unit runner).
"""

from __future__ import annotations

import anyio
import pytest

from moat.dev.heat.link import ServiceMonitor
from moat.dev.heat.system.runner import DEFAULT, ERROR_PATH, UNITS, run_units
from moat.lib.path import P

from typing import Any


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
        "passthru",
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


class Flaky:
    "a unit that fails a few times, then runs"

    name = "flaky"
    fails = 0
    runs = 0
    kw: dict[str, Any] = {}

    def __init__(self, link) -> None:
        self.link = link

    async def run(self, *, task_status, **kw: Any) -> None:
        "fail, or run"
        cls = type(self)
        cls.kw = kw
        if cls.fails:
            cls.fails -= 1
            raise RuntimeError("flaky")
        cls.runs += 1
        task_status.started()
        await anyio.sleep_forever()


ERR = P("error") + ERROR_PATH / "flaky"


@pytest.fixture
def flaky(monkeypatch):
    "the runner knows the `Flaky` unit"
    monkeypatch.setitem(UNITS, "flaky", Flaky)
    Flaky.fails = 2
    Flaky.runs = 0
    return Flaky


@pytest.mark.anyio
async def test_retry(heat, flaky, caplog) -> None:
    "a failing unit is logged, reported to MoaT-Link, and restarted with backoff"
    await heat.seed_config(
        "service", {"backoff": {"min": 0.2, "max": 0.3, "factor": 2}, "recovery": 0.3}
    )
    async with anyio.create_task_group() as tg:
        t0 = anyio.current_time()
        with anyio.fail_after(2):
            # "ready" doesn't wait for the unit to work
            await tg.start(
                lambda *, task_status: run_units(
                    heat.sf.client_, ["flaky"], retry=True, task_status=task_status
                )
            )
        assert flaky.runs == 0
        err = await heat.expect(ERR, lambda v: v is not None)
        assert "flaky" in repr(err)

        with anyio.fail_after(3):
            while not flaky.runs:  # noqa: ASYNC110
                await anyio.sleep(0.05)
        # two failures: 0.2 + 0.3 seconds of backoff
        assert anyio.current_time() - t0 >= 0.45
        assert flaky.fails == 0
        assert flaky.kw["force"] is False
        assert "Unit flaky failed" in caplog.text

        # … and the error is cleared once it has been running for a while
        await heat.expect(ERR, lambda v: v is None or v.get("ok"))
        tg.cancel_scope.cancel()


@pytest.mark.anyio
async def test_no_retry(heat, flaky) -> None:
    "named units: a failure is reported to MoaT-Link and propagates"
    with pytest.raises(BaseExceptionGroup) as exc, anyio.fail_after(2):
        await run_units(heat.sf.client_, ["flaky"], force=True)
    assert exc.value.subgroup(RuntimeError) is not None
    assert flaky.kw["force"] is True
    assert flaky.fails == 1
    await heat.expect(ERR, lambda v: v is not None)


@pytest.mark.anyio
async def test_wait_and_force(heat) -> None:
    "a second runner waits for the unit's service, unless it is forced"
    async with anyio.create_task_group() as tg:
        await tg.start(
            lambda *, task_status: run_units(
                heat.sf.client_, ["target"], retry=True, task_status=task_status
            )
        )
        # waiting counts as "ready"
        with anyio.fail_after(2):
            await tg.start(
                lambda *, task_status: run_units(
                    heat.sf.client_, ["target"], retry=True, task_status=task_status
                )
            )
        ann = await heat.link.d_get(P("run.host.heat.heat.target"))

        with anyio.fail_after(2):
            await tg.start(
                lambda *, task_status: run_units(
                    heat.sf.client_, ["target"], force=True, task_status=task_status
                )
            )
        new = await heat.expect(
            P("run.host.heat.heat.target"), lambda v: v is not None and v["id"] != ann["id"]
        )
        assert new["up"]
        tg.cancel_scope.cancel()


async def test_cli_help(capfd) -> None:
    "``moat dev heat run`` exists"
    from moat.src.test import run  # noqa: PLC0415

    # (not "moat dev heat --help": listing the commands imports the legacy
    # module, which messes with the global configuration)
    await run("dev", "heat", "run", "--help", do_stdout=False)
    out = capfd.readouterr().out
    # every unit is listed, with what it does
    for name in UNITS:
        assert name in out
    assert "Decide which heat sources may run." in out
    assert "watchdog (not by default)" in out
