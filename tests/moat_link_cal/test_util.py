"""Tests for moat.link.cal utility functions."""

from __future__ import annotations

from datetime import UTC, datetime

from moat.link.cal.util import next_start


def test_next_start_no_rrule():
    """Without an rrule, the start time is returned as-is."""

    class _V:
        dtstart = type("_DT", (), {"value": datetime(2026, 1, 1, 12, 0, tzinfo=UTC)})()
        contents = {}

    v = _V()
    now = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    result = next_start(v, now)
    assert result == datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def test_next_start_with_future_date():
    """A start time in the future is returned directly when there is no rrule."""

    class _V:
        dtstart = type("_DT", (), {"value": datetime(2026, 7, 1, 9, 0, tzinfo=UTC)})()
        contents = {}

    v = _V()
    now = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    result = next_start(v, now)
    assert result == datetime(2026, 7, 1, 9, 0, tzinfo=UTC)
