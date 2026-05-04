"""
Test the Control wrapper: state-machine and resync logic.

Control is a pure state machine: it converts an input in [0..base] into
an output in [0..1].  Forwarding the result to a PWM (or any other
consumer) is not part of Control's job, so these tests inspect the
output via ``cmd_s`` rather than wiring up a sink.
"""
# ruff:noqa:SLF001

from __future__ import annotations

import anyio
import pytest
from unittest.mock import patch

import moat.micro.part.control as control_module
from moat.lib.micro import Event, sleep_ms
from moat.lib.path import P
from moat.lib.rpc._test import rpc_stack
from moat.micro.part.control import Control


class FControl(Control):
    "Monkeyhacked Control class — exercises resync state machine without RPC."

    def __init__(
        self,
        base,
        sync_low=None,
        sync_high=None,
        sync_path=None,
        sync_invert=False,
    ):
        self.base = base
        self.value = 0.0
        self.force = None
        self.out = 0.0
        self.out_evt = Event()
        self.sync_low = sync_low or self._sync_defaults()
        self.sync_high = sync_high or self._sync_defaults()
        self.sync_path = sync_path
        self.sync_invert = sync_invert
        self._sync_pid = None
        self._out_mode = None
        self._sync_active = None
        self._sync_left = None
        self._sync_suspended = False
        self._sync_check_ms = None
        self._tg = None

    @staticmethod
    def _sync_defaults(**kw):
        d = dict(threshold=None, input=None, t_sync=None, t_check=10, bound=None, lock=False)
        d.update(kw)
        return d


# ---------------------------------------------------------------------------
# Unit tests on the resync state machine (no RPC)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_resync_cancelled_by_threshold():
    "Resync ends when the value drops below the low threshold."
    mock_time = 0

    def fake_ticks_ms():
        return mock_time

    with patch.object(control_module, "ticks_ms", fake_ticks_ms):
        p = FControl(
            base=100,
            sync_low=FControl._sync_defaults(threshold=10, input=50, t_sync=0.05),
        )

        await p._set_value(5, False)
        await p._set_value(20, False)
        assert p._sync_active == "low"

        await p._set_value(5, False)
        assert p._sync_active is None
        assert p._out_mode == "low"
        assert p.out == 0.0


@pytest.mark.anyio
async def test_resync_no_input():
    "No resync occurs when the low input clamp is unset."
    p = FControl(base=100, sync_low=FControl._sync_defaults(threshold=10))

    await p._set_value(5, False)
    await p._set_value(20, False)
    assert p._sync_active is None
    assert p._out_mode is None
    assert p.out == pytest.approx(20 / 100)


# ---------------------------------------------------------------------------
# End-to-end tests — outputs are inspected via cmd_s["out"].
# ---------------------------------------------------------------------------

E2E_CTRL_CFG = """
app: dir
w:
  app: part.Control
  base: 100
"""


@pytest.mark.anyio
async def test_e2e_ctrl_read(tmp_path):
    "cmd_r returns the current [0..1] output; force overrides the normal value"
    async with rpc_stack(tmp_path, E2E_CTRL_CFG) as d, anyio.create_task_group() as tg:
        w = d.sub_at(P("w"))

        @tg.start_soon
        async def rdr():
            assert await w.r() == pytest.approx(0.42)
            assert await w.r() == pytest.approx(0.77)
            assert await w.r() == pytest.approx(0.42)

        await anyio.sleep(0.01)

        await w.w(42)
        await anyio.sleep(0.01)

        # Force a different value; cmd_r must reflect it.
        await w.w(77, f=True)
        await anyio.sleep(0.01)

        # Clear the force; cmd_r reverts to the underlying value.
        await w.w(None, f=True)
        await anyio.sleep(0.01)


@pytest.mark.anyio
async def test_e2e_ctrl_read_blocks(tmp_path):
    "cmd_r blocks until the next _apply_value updates the output."
    async with rpc_stack(tmp_path, E2E_CTRL_CFG) as d:
        w = d.sub_at(P("w"))

        # Spawn cmd_r in the background; it must block until w.w() runs.
        async with anyio.create_task_group() as tg:
            result: list[float] = []

            @tg.start_soon
            async def _read():
                result.append(await w.r())

            await sleep_ms(30)
            assert result == []  # still blocking

            await w.w(50)
            await sleep_ms(20)  # let cmd_r unblock
            assert result == [pytest.approx(0.5)]


# ---------------------------------------------------------------------------
# Resync end-to-end tests
# ---------------------------------------------------------------------------

E2E_SYNC_LOW_CFG = """
app: dir
w:
  app: part.Control
  base: 100
  sync_low:
    threshold: 20
    input: 50
"""

E2E_SYNC_HIGH_CFG = """
app: dir
w:
  app: part.Control
  base: 100
  sync_high:
    threshold: 80
    input: 50
"""

E2E_SYNC_SUSP_CFG = """
app: dir
w:
  app: part.Control
  base: 100
  sync_low:
    threshold: 20
    input: 50
    t_sync: 2.0
    t_check: 0.05
    bound: 0.5
  sync_path: !P sp
sp:
  app: _fake.Pin
  pin: SP
"""

E2E_RESYNC_TIMER_CFG = """
app: dir
w:
  app: part.Control
  base: 100
  sync_high:
    threshold: 80
    input: 10
    t_sync: 0.15
"""


@pytest.mark.anyio
async def test_e2e_resync_timer(tmp_path):
    "t_sync expires the resync independently of any consumer behaviour."
    async with rpc_stack(tmp_path, E2E_RESYNC_TIMER_CFG) as d:
        w = d.sub_at(P("w"))

        # val=90 → above threshold=80 → out_mode="high" → output forced to 1.0.
        await w.w(90)
        assert (await w.s())["out"] == pytest.approx(1.0)

        # val=25 → resync starts: effective=min(25, input=10)=10 → 0.10.
        await w.w(25)
        s = await w.s()
        assert s["out"] == pytest.approx(0.10)
        assert s["resync"]["mode"] == "high"

        # After t_sync=150 ms the resync ends and the unclamped value is sent.
        await sleep_ms(200)
        s = await w.s()
        assert "resync" not in s
        assert s["out"] == pytest.approx(0.25)


@pytest.mark.anyio
async def test_e2e_resync_low(tmp_path):
    "sync_low: below threshold → out=0; crossing above → clamped output, then normal"
    async with rpc_stack(tmp_path, E2E_SYNC_LOW_CFG) as d:
        w = d.sub_at(P("w"))

        # Below threshold=20 → output forced low.
        await w.w(10)
        s = await w.s()
        assert s["out"] == pytest.approx(0.0)
        assert s["out_mode"] == "low"

        # Cross above threshold: resync starts; effective = max(30, 50) = 50.
        await w.w(30)
        s = await w.s()
        assert s["out"] == pytest.approx(0.5)
        assert s["resync"]["mode"] == "low"

        # Raise val above input=50 → resync ends immediately (no t_sync timer).
        await w.w(60)
        s = await w.s()
        assert s["out"] == pytest.approx(0.6)
        assert "resync" not in s


@pytest.mark.anyio
async def test_e2e_resync_high(tmp_path):
    "sync_high: above threshold → out=1; crossing below → clamped output, then normal"
    async with rpc_stack(tmp_path, E2E_SYNC_HIGH_CFG) as d:
        w = d.sub_at(P("w"))

        # Above threshold=80 → output forced high.
        await w.w(90)
        s = await w.s()
        assert s["out"] == pytest.approx(1.0)
        assert s["out_mode"] == "high"

        # Cross below threshold: resync starts; effective = min(70, 50) = 50.
        await w.w(70)
        s = await w.s()
        assert s["out"] == pytest.approx(0.5)
        assert s["resync"]["mode"] == "high"

        # Drop val below input=50 → resync ends immediately.
        await w.w(40)
        s = await w.s()
        assert s["out"] == pytest.approx(0.4)
        assert "resync" not in s


@pytest.mark.anyio
async def test_e2e_resync_cancelled(tmp_path):
    "resync is cancelled immediately when the value drops back below the low threshold"
    async with rpc_stack(tmp_path, E2E_SYNC_LOW_CFG) as d:
        w = d.sub_at(P("w"))

        await w.w(10)

        await w.w(30)  # start resync
        assert (await w.s())["resync"]["mode"] == "low"

        await w.w(5)  # back below threshold → resync cancelled, out_mode restored
        s = await w.s()
        assert "resync" not in s
        assert s["out_mode"] == "low"
        assert s["out"] == pytest.approx(0.0)


@pytest.mark.anyio
async def test_e2e_resync_suspended(tmp_path):
    "sync_path reading above bound suspends the resync clamp; below bound resumes it"
    async with rpc_stack(tmp_path, E2E_SYNC_SUSP_CFG) as d:
        w = d.sub_at(P("w"))
        sp = d.sub_at(P("sp"))

        await w.w(10)

        await w.w(30)  # start resync; effective output = max(30, 50)/100 = 0.50
        s = await w.s()
        assert s["resync"]["mode"] == "low"
        assert s["out"] == pytest.approx(0.5)

        # sp=True → value=1 > bound=0.5 → resync suspended after next t_check.
        # While suspended, the unclamped value is sent: 30/100 = 0.30.
        await sp(True)
        await sleep_ms(60)  # one t_check interval (50 ms) passes
        s = await w.s()
        assert s["resync"]["suspended"] is True
        assert s["out"] == pytest.approx(0.3)

        # sp=False → value=0 < bound=0.5 → resync resumes after next t_check.
        await sp(False)
        await sleep_ms(60)
        s = await w.s()
        assert s["resync"]["suspended"] is False
        assert s["out"] == pytest.approx(0.5)
