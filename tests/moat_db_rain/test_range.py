"""Tests for the interval-algebra primitives in :mod:`moat.db.rain.range`.

The first three tests port the legacy ``rainman/utils.py`` ``__main__``
self-test verbatim (plain ints — the arithmetic is duck-typed, so int
tuples exercise the algorithm exactly as the legacy code did). The
remaining tests cover the datetime-typed path the engine uses, plus
edge cases (empty inputs, touching/adjacent intervals, ``StoredIter``
peek/advance semantics).
"""

from __future__ import annotations

import pytest
from datetime import UTC, datetime, timedelta

from moat.db.rain.range import (
    RangeMixin,
    StoredIter,
    range_coalesce,
    range_intersection,
    range_invert,
    range_union,
)

# Sample interval sets from the legacy ``rainman/utils.py`` self-test.
_A = ((1, 100), (220, 100), (350, 100), (500, 100))
_B = ((2, 50), (60, 100), (320, 80), (510, 110))
_C = ((0, 10), (11, 2), (70, 1000))


def test_selftest_intersection_is_order_invariant():
    """All argument orders of a 3-way intersection yield the same result."""
    expected = [(2, 8), (11, 2), (70, 31), (350, 50), (510, 90)]
    for perm in (
        (_A, _B, _C),
        (_C, _B, _A),
        (_C, _A, _B),
        (_A, _C, _B),
        (_B, _C, _A),
        (_B, _A, _C),
    ):
        assert list(range_intersection(*perm)) == expected


def test_selftest_invert():
    """Subtracting _A from [50,1000) leaves the gaps between its intervals."""
    assert list(range_invert(50, 950, _A)) == [
        (101, 119),
        (320, 30),
        (450, 50),
        (600, 400),
    ]


def test_selftest_union():
    """Union of _A and _B merges overlaps and touching intervals."""
    assert list(range_union(_A, _B)) == [(1, 159), (220, 230), (500, 120)]


_BASE = datetime(2030, 1, 1, tzinfo=UTC)
_HOUR = timedelta(hours=1)


def _to_dt(seqs):
    """Scale int ``(start, length)`` tuples to datetime/timedelta ones."""
    return [(_BASE + s * _HOUR, ln * _HOUR) for s, ln in seqs]


def _from_dt(seqs):
    """Scale datetime/timedelta results back to int ``(start, length)`` tuples."""
    return [(round((s - _BASE) / _HOUR), round(ln / _HOUR)) for s, ln in seqs]


def test_datetime_path_matches_int_selftest():
    """The datetime-typed path reproduces the int self-test (hours as units)."""
    expected = [(2, 8), (11, 2), (70, 31), (350, 50), (510, 90)]
    got = _from_dt(list(range_intersection(_to_dt(_A), _to_dt(_B), _to_dt(_C))))
    assert got == expected

    assert _from_dt(list(range_invert(_BASE + 50 * _HOUR, 950 * _HOUR, _to_dt(_A)))) == [
        (101, 119),
        (320, 30),
        (450, 50),
        (600, 400),
    ]
    assert _from_dt(list(range_union(_to_dt(_A), _to_dt(_B)))) == [
        (1, 159),
        (220, 230),
        (500, 120),
    ]


def test_coalesce_merges_overlaps_touch_and_gaps():
    """Coalesce merges overlapping and touching intervals, splits on gaps."""
    assert list(range_coalesce(((1, 5), (2, 3), (10, 5)))) == [(1, 5), (10, 5)]
    # touching (end == next start) merges
    assert list(range_coalesce(((1, 5), (6, 4)))) == [(1, 9)]
    # fully contained interval absorbed
    assert list(range_coalesce(((1, 10), (3, 2)))) == [(1, 10)]
    # single interval
    assert list(range_coalesce(((1, 5),))) == [(1, 5)]
    # empty input yields nothing
    assert list(range_coalesce(())) == []


def test_union_drops_empty_inputs():
    """Empty inputs contribute nothing to the union."""
    assert list(range_union(_A, (), _B)) == [(1, 159), (220, 230), (500, 120)]
    assert list(range_union((), ())) == []


def test_intersection_with_empty_input_is_empty():
    """Intersecting with an empty sequence yields no intervals."""
    assert list(range_intersection(_A, ())) == []
    assert list(range_intersection((), _A, _B)) == []


def test_invert_edges():
    """Invert against a covering set, an empty set, a leading interval, and tails."""
    # a covers [10,90) entirely → no gaps
    assert list(range_invert(10, 80, ((5, 90),))) == []
    # a empty → the whole interval is returned
    assert list(range_invert(10, 80, ())) == [(10, 80)]
    # leading interval clips the front, leaving [20,90)
    assert list(range_invert(10, 80, ((0, 20),))) == [(20, 70)]
    # interval entirely past the end → whole window returned (tail preserved)
    assert list(range_invert(10, 80, ((100, 5),))) == [(10, 80)]
    # a later interval past the end → the tail gap is still yielded
    assert list(range_invert(10, 80, ((20, 10), (100, 5)))) == [(10, 10), (30, 60)]
    # interval entirely before ra is skipped, then a middle one is subtracted
    assert list(range_invert(50, 100, ((0, 10), (60, 5)))) == [(50, 10), (65, 85)]


def test_stored_iter_peek_and_advance():
    """``stored`` peeks without consuming; ``next`` advances and returns."""
    s = StoredIter([1, 2, 3])
    assert s.stored == 1
    assert s.stored == 1  # repeated peek does not advance
    assert s.next == 2
    assert s.stored == 2  # stored tracks the advanced head
    assert s.next == 3
    assert s.stored == 3
    with pytest.raises(StopIteration):
        _ = s.next


def test_stored_iter_empty_raises_stop_iteration():
    """An empty ``StoredIter`` raises on first peek or advance."""
    s = StoredIter([])
    with pytest.raises(StopIteration):
        _ = s.stored
    with pytest.raises(StopIteration):
        _ = StoredIter([]).next


def test_intersection_no_args_is_empty():
    """Intersecting no sequences yields no intervals."""
    assert list(range_intersection()) == []


class _RecordingRange(RangeMixin):
    """A :class:`RangeMixin` stub that records the window and replays spans."""

    def __init__(self, spans):
        self.spans = spans
        self.seen = None

    def _range(self, start, end, **k):
        self.seen = (start, end, k)
        yield from self.spans


class _ErrRange(RangeMixin):
    """A :class:`RangeMixin` stub whose ``_range`` raises on iteration."""

    def _range(self, start, end, **k):
        _ = (start, end, k)
        raise ValueError("bad")
        yield  # marker: makes _range a generator so the error raises on iteration


def test_range_mixin_window_forwards_to_range():
    """``range()`` defaults the window and forwards (start, end) to ``_range()``."""
    stub = _RecordingRange([(_BASE, _HOUR), (_BASE + 2 * _HOUR, _HOUR)])
    got = list(stub.range(start=_BASE, days=5))
    assert got == [(_BASE, _HOUR), (_BASE + 2 * _HOUR, _HOUR)]
    assert stub.seen == (_BASE, _BASE + timedelta(days=5), {})


def test_range_mixin_list_range_formats_and_truncates():
    """``list_range`` pretty-prints the first three intervals, truncating with …."""
    spans = [
        (_BASE, _HOUR),
        (_BASE + 2 * _HOUR, _HOUR),
        (_BASE + 4 * _HOUR, _HOUR),
        (_BASE + 6 * _HOUR, _HOUR),
    ]
    txt = _RecordingRange(spans).list_range()
    assert "…" in txt
    assert _BASE.isoformat() in txt

    # fewer than three → no truncation marker
    short = [(_BASE, _HOUR), (_BASE + 2 * _HOUR, _HOUR)]
    assert "…" not in _RecordingRange(short).list_range()


def test_range_mixin_list_range_traps_value_error():
    """``list_range`` reports ‹Error› when ``_range`` raises :class:`ValueError`."""
    assert _ErrRange().list_range() == "‹Error›"


def test_range_mixin_base_range_is_not_implemented():
    """The base ``_range`` raises :class:`NotImplementedError`."""
    with pytest.raises(NotImplementedError):
        list(RangeMixin().range(start=_BASE, days=1))
