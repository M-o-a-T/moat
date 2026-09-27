"""
Tests for the heat controller's unit adapter, using a trivial core.
"""

from __future__ import annotations

import anyio
import pytest

from moat.dev.heat.config import CFG_PATH, UnitCfg
from moat.dev.heat.link import Reader, ServiceMonitor
from moat.dev.heat.state import State, state_path
from moat.dev.heat.unit import Step, Unit
from moat.lib.path import P, Path

from typing import Any

pytestmark = pytest.mark.anyio

TMO = 2
SRC = P("test.unit.src")
DST = P("test.unit.dst")


class TCfg(UnitCfg):
    "test config"

    src: Path = SRC
    dst: Path = DST
    factor: int = 1
    tick: float | None = None


class TState(State):
    "test state"

    steps: int = 0


class TCore:
    "multiplies its input, counts its steps"

    def __init__(self, cfg: TCfg, state: TState) -> None:
        self.cfg = cfg
        self.state = state

    def update_cfg(self, cfg: TCfg) -> None:
        "new config"
        self.cfg = cfg

    def step(self, inputs: dict[str, Any], now: float) -> Step:  # noqa: ARG002
        "one step"
        self.state.steps += 1
        return Step(
            outputs={self.cfg.dst: (inputs["src"] or 0) * self.cfg.factor},
            wake_in=self.cfg.tick,
            save_now=True,
        )


class TUnit(Unit[TCfg, TState]):
    "test unit"

    name = "test"
    cfg_model = TCfg
    state_model = TState

    def make_core(self, cfg: TCfg, state: TState, now: float) -> TCore:  # noqa: ARG002
        "the core"
        return TCore(cfg, state)

    def make_inputs(self, cfg: TCfg) -> dict[str, Reader[Any]]:
        "one input"
        return {"src": Reader[int](self.link, cfg.src)}


async def _until(r: Reader[Any], pred) -> None:
    with anyio.fail_after(TMO):
        while not pred(r.value):
            await r.wait_changed()


async def test_unit(link):
    "announcement, input-driven steps, config change, state"
    out = Reader[int](link, DST)
    sm = ServiceMonitor(link, "heat", "test")
    async with anyio.create_task_group() as tg:
        await tg.start(out.run)
        await tg.start(sm.run)
        await tg.start(TUnit(link).run)

        await _until(sm, lambda _: sm.alive)
        await _until(out, lambda v: v == 0)

        await link.d_set(SRC, 2, retain=True)
        await _until(out, lambda v: v == 2)

        await link.d_set(CFG_PATH / "test", {"factor": 3}, retain=True, verify=False)
        await _until(out, lambda v: v == 6)

        await link.i_sync()
        st = await link.d_get(state_path("test"))
        assert st["steps"] >= 3
        tg.cancel_scope.cancel()


async def test_wake_in(link):
    "the core is called again after `wake_in` without input changes"
    await link.d_set(CFG_PATH / "test", {"tick": 0.1}, retain=True, verify=False)
    st = Reader[dict](link, state_path("test"))
    async with anyio.create_task_group() as tg:
        await tg.start(st.run)
        await tg.start(TUnit(link).run)
        await _until(st, lambda v: v is not None and v["steps"] >= 5)
        tg.cancel_scope.cancel()
