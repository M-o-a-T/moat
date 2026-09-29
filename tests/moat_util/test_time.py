"""Tests for the overridable clock in :mod:`moat.util.time`."""

from __future__ import annotations

import anyio
import pytest
import time

from moat.util import time as mtime
from moat.util.time import loop_time, monotonic, patch_clock, set_clock


def test_defaults_track_stdlib() -> None:
    """Unmodified slots agree with the standard-library functions."""
    assert mtime.time() == pytest.approx(time.time(), abs=1.0)
    assert monotonic() == pytest.approx(time.monotonic(), abs=1.0)


def test_set_clock_override_and_reset() -> None:
    """``set_clock`` swaps each slot independently; ``None`` resets it."""
    sentinel_t = 1234.5
    sentinel_m = 6789.0

    set_clock(time=lambda: sentinel_t)
    assert mtime.time() == sentinel_t
    assert monotonic() == pytest.approx(time.monotonic(), abs=1.0)

    set_clock(monotonic=lambda: sentinel_m)
    assert mtime.time() == sentinel_t
    assert monotonic() == sentinel_m

    set_clock(time=None)
    assert mtime.time() == pytest.approx(time.time(), abs=1.0)
    assert monotonic() == sentinel_m

    set_clock(monotonic=None)
    assert mtime.time() == pytest.approx(time.time(), abs=1.0)
    assert monotonic() == pytest.approx(time.monotonic(), abs=1.0)


def test_patch_clock_restores_on_normal_exit() -> None:
    """``patch_clock`` restores the prior slots after a normal exit."""
    before_t = mtime.time()
    before_m = monotonic()

    with patch_clock(time=lambda: 42.0, monotonic=lambda: 7.0):
        assert mtime.time() == 42.0
        assert monotonic() == 7.0

    assert mtime.time() == pytest.approx(before_t, abs=1.0)
    assert monotonic() == pytest.approx(before_m, abs=1.0)


def test_patch_clock_restores_on_exception() -> None:
    """``patch_clock`` restores the prior slots even when the body raises."""
    before_t = mtime.time()
    before_m = monotonic()

    with patch_clock(time=lambda: 42.0, monotonic=lambda: 7.0):
        assert mtime.time() == 42.0
        with pytest.raises(ValueError, match="boom"):
            raise ValueError("boom")

    assert mtime.time() == pytest.approx(before_t, abs=1.0)
    assert monotonic() == pytest.approx(before_m, abs=1.0)


def test_patch_clock_partial_override() -> None:
    """Patching only ``time`` leaves ``monotonic`` on its current value."""
    before_m = monotonic()

    with patch_clock(time=lambda: 99.0):
        assert mtime.time() == 99.0
        assert monotonic() == pytest.approx(before_m, abs=1.0)

    assert mtime.time() != 99.0


def test_patch_clock_nested() -> None:
    """Nested patches unwind in reverse order, restoring intermediate state."""
    outer_marker = lambda: 1.0  # noqa: E731
    inner_marker = lambda: 2.0  # noqa: E731

    with patch_clock(time=outer_marker):
        assert mtime.time() == 1.0
        with patch_clock(time=inner_marker):
            assert mtime.time() == 2.0
        assert mtime.time() == 1.0
    assert mtime.time() != 1.0


def test_loop_time_outside_event_loop() -> None:
    """Without a running loop, ``loop_time`` falls back to ``monotonic``."""
    marker = lambda: 555.0  # noqa: E731
    with patch_clock(monotonic=marker):
        assert loop_time() == 555.0


async def test_loop_time_tracks_anyio_clock() -> None:
    """Inside a runner, ``loop_time`` follows the event-loop clock."""
    t0 = loop_time()
    await anyio.sleep(0.01)
    t1 = loop_time()
    assert t1 > t0


async def test_patch_clock_restores_on_cancellation() -> None:
    """Cancellation unwinds ``patch_clock`` via the ``finally`` arm."""

    results: dict[str, float] = {}

    async def child() -> None:
        with patch_clock(time=lambda: 321.0):
            results["inside"] = mtime.time()
            await anyio.sleep_forever()

    before = mtime.time()
    async with anyio.create_task_group() as tg:
        tg.start_soon(child)
        await anyio.sleep(0.02)  # let the child enter the patched block
        tg.cancel_scope.cancel()

    assert results["inside"] == 321.0
    assert mtime.time() == pytest.approx(before, abs=1.0)
