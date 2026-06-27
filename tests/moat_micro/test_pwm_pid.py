"""
Test the Control–PID lock integration: when sync_low is active and the
sync_path sensor is below the bound, the PID's I term must not increase
(anti-windup protection).  When the sensor crosses above the bound
(resync suspended), the lock releases and the I term is free to change.
"""

from __future__ import annotations

import pytest

from moat.lib.micro import sleep_ms
from moat.lib.path import P
from moat.lib.rpc._test import rpc_stack

# PWM: base=100, min=50ms, max=500ms
# sync_low: threshold=20, input=50, t_sync=10s (long, won't expire in test),
#           t_check=50ms, bound=0.5, lock=true
# sync_pid: points to the PID at !P pid
# PID: pure integrator (p=0, i=1.0), setpoint=1.0 → error=1.0-val
#
# With val=0 passed to pid.w:
#   error = 1.0 - 0.0 = 1.0
#   Ki = 1.0 / PID_TC (= 1.0 in standard Python, where time is in seconds)
#   dt = 0.1 s  →  Δi = 0.1 * 1.0 * 1.0 = 0.1

E2E_PID_LOCK_CFG = """
app: dir
pid:
  app: part.PID
  p: 0.0
  i: 1.0
  d: 0.0
  set: 1
w:
  app: part.Control
  base: 100
  sync_low:
    threshold: 20
    input: 50
    t_sync: 10.0
    t_check: 0.05
    bound: 0.5
    lock: true
  sync_path: !P sp
  sync_pid: !P pid
sp:
  app: _fake.Pin
  pin: SP
"""


@pytest.mark.anyio
async def test_pid_lock_prevents_integral_windup(tmp_path):
    """
    Verify that the PID I term does not increase while the PWM sync lock
    is active (sync_path below bound), and that it is free to increase
    once the lock is released (sync_path above bound / resync suspended).
    """
    async with rpc_stack(tmp_path, E2E_PID_LOCK_CFG) as d:
        w = d.sub_at(P("w"))
        pid = d.sub_at(P("pid"))
        sp = d.sub_at(P("sp"))

        # Anchor in always-off (below sync_low.threshold=20).
        await w.w(0)
        await sleep_ms(70)

        # Reset PID time so we can use explicit timestamps reliably.
        # sp defaults to False (= 0.0 < bound=0.5) → not suspended.
        await pid.s(t=0.0, i=0.0)

        # Raise PWM above threshold=20 → resync starts.
        # _resync_countdown spawns and immediately starts the PID lock
        # (sp=0 < 0.5 → not suspended → output is forced).
        await w.w(30)
        await sleep_ms(30)  # let the scheduler establish the lock stream

        # --- PID should be locked (I must not exceed lock-entry value of 0) ---
        # Call with positive error (setpoint=1, val=0 → error=1): would increase I.
        await pid.w(0.0, t=0.0)  # dt=0, no change; lock-entry I = 0
        await pid.w(0.0, t=0.1)  # dt=0.1 s; without lock Δi=0.1, with lock clamped to 0
        i_locked = (await pid.s())["state"]["i"]
        assert i_locked == pytest.approx(0.0), (
            f"I increased while locked: expected 0, got {i_locked}"
        )

        # I can still decrease below the lock-entry value (anti-windup is allowed).
        # Call with negative error (val > setpoint → error < 0): would decrease I.
        await pid.w(2.0, t=0.2)  # error = 1-2 = -1 → Δi = -0.1; lock does not block
        i_below = (await pid.s())["state"]["i"]
        assert i_below < i_locked, (
            f"I didn't decrease below lock-entry when error negative: {i_locked} → {i_below}"
        )

        # And must still not exceed the lock-entry value (0) even after dipping below.
        await pid.w(0.0, t=0.3)  # back to positive error; must stay ≤ 0
        i_still_capped = (await pid.s())["state"]["i"]
        assert i_still_capped == pytest.approx(0.0), (
            f"I exceeded lock-entry value after dip: {i_still_capped}"
        )

        # --- Release lock: sp=True (1.0 > 0.5) → suspended after t_check ---
        await sp(True)
        await sleep_ms(80)  # one t_check interval (50 ms) + margin

        # Confirm resync is now suspended.
        s = await w.s()
        assert s["resync"]["suspended"] is True

        # Allow the lock-release to propagate (PID stream_lock finally block).
        await sleep_ms(20)

        # --- PID should be free; I must increase ---
        await pid.w(0.0, t=0.4)  # dt=0.1 s → Δi=0.1 (t must be > 0.3)
        i_free = (await pid.s())["state"]["i"]
        assert i_free > i_locked, f"I did not increase after lock released: {i_locked} → {i_free}"


@pytest.mark.anyio
async def test_pid_lock_released_on_resync_end(tmp_path):
    """
    Verify that the PID lock is released when the resync ends (PWM value
    drops back below the threshold, cancelling the resync).
    """
    async with rpc_stack(tmp_path, E2E_PID_LOCK_CFG) as d:
        w = d.sub_at(P("w"))
        pid = d.sub_at(P("pid"))

        await w.w(0)
        await sleep_ms(70)

        await pid.s(t=0.0, i=0.0)

        # Start resync → lock starts.
        await w.w(30)
        await sleep_ms(30)

        # Confirm lock is in effect.
        await pid.w(0.0, t=0.0)
        await pid.w(0.0, t=0.1)
        i_locked = (await pid.s())["state"]["i"]
        assert i_locked == pytest.approx(0.0)

        # Drop below threshold → resync cancelled → lock must be released.
        await w.w(5)
        s = await w.s()
        assert "resync" not in s
        assert s["out_mode"] == "low"

        # Give the lock-release a scheduler pass to propagate.
        await sleep_ms(20)

        # I term must now be free to increase.
        await pid.w(0.0, t=0.2)
        i_free = (await pid.s())["state"]["i"]
        assert i_free > i_locked, (
            f"I did not increase after resync cancelled: {i_locked} → {i_free}"
        )
