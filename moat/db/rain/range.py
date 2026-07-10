"""Interval-algebra primitives for the rain scheduler.

Ported from the legacy ``rainman/utils.py``. Pure iterators over
``(start, length)`` tuples — ``start`` is a :class:`~datetime.datetime`
and ``length`` a :class:`~datetime.timedelta` (the unit the engine
integrates over). The legacy self-test used plain ints for legibility;
the arithmetic is duck-typed, so ``tests/moat_db_rain/test_range.py``
keeps that int-based regression check alongside a datetime-scaled one.

The module has no ORM dependency.

Conventions:

* Intervals are half-open ``[start, start+length)``.
* Every input sequence must be **sorted by start**; :func:`range_coalesce`
  asserts this. The engine's ``_range()`` generators walk forward in
  time, so their output is naturally sorted.
* Touching intervals (``prev_end == next_start``) are merged.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from moat.util.times import now

from typing import TYPE_CHECKING, Any, Generic, TypeVar

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

__all__ = [
    "RangeMixin",
    "StoredIter",
    "range_coalesce",
    "range_intersection",
    "range_invert",
    "range_union",
]

#: A ``(start, length)`` interval.
_Span = tuple[datetime, timedelta]

T = TypeVar("T")


class StoredIter(Generic[T]):
    """A peekable iterator wrapping an iterable.

    Exposes two properties, ported from the legacy ``StoredIter``:

    * :attr:`stored` — the current head item, fetched lazily on first
      access (peek without consuming).
    * :attr:`next` — advance to the next item and return it.

    Both raise :class:`StopIteration` when the underlying iterator is
    exhausted; callers (the union/intersection mergers) catch that to
    drop or terminate the stream.
    """

    def __init__(self, it: Iterable[T]) -> None:
        self._it: Iterator[T] = iter(it)
        self._saved: T | None = None
        self._fetched = False

    @property
    def next(self) -> T:
        """Advance past the current head and return the new one."""
        s = next(self._it)
        self._saved = s
        self._fetched = True
        return s

    @property
    def stored(self) -> T:
        """The current head item, fetched lazily if not yet seen."""
        if not self._fetched:
            self._saved = next(self._it)
            self._fetched = True
        s = self._saved
        assert s is not None
        return s


def range_coalesce(it: Iterable[_Span]) -> Iterator[_Span]:
    """Coalesce a sorted sequence of overlapping/adjacent intervals.

    Args:
        it: ``(start, length)`` tuples sorted by ``start``.

    Yields:
        Merged ``(start, length)`` tuples covering the same span.

    Raises:
        AssertionError: if the input is not sorted by ``start``.
    """
    it = iter(it)
    try:
        ra, rl = next(it)
    except StopIteration:
        return
    while True:
        try:
            sa, sl = next(it)
        except StopIteration:
            yield ra, rl
            return
        assert ra <= sa, (ra, rl, sa, sl)
        re = ra + rl
        se = sa + sl
        if re < sa:
            yield ra, rl
            ra, rl = sa, sl
            continue
        if re < se:
            rl = se - ra


def range_union(*a: Iterable[_Span]) -> Iterator[_Span]:
    """Union of several sorted interval sequences.

    Each input is coalesced, then the streams are merged and the result
    is coalesced again. Empty inputs are dropped.
    """
    return range_coalesce(_range_union([StoredIter(range_coalesce(ax)) for ax in a]))


def _range_union(head: list[StoredIter[_Span]]) -> Iterator[_Span]:
    """K-way merge of coalesced, sorted streams into one sorted stream."""
    while head:
        best: tuple[StoredIter[_Span], datetime, timedelta, int] | None = None
        i = 0
        while i < len(head):
            ax = head[i]
            try:
                sa, sl = ax.stored
            except StopIteration:
                del head[i]
                continue
            if best is None or sa < best[1]:
                best = (ax, sa, sl, i)
            i += 1
        if best is None:
            break
        ax, ra, rl, ri = best
        yield ra, rl
        try:
            _ = ax.next
        except StopIteration:
            del head[ri]


def range_intersection(*a: Iterable[_Span]) -> Iterator[_Span]:
    """Intersection of several sorted interval sequences.

    Each input is coalesced, then the heads are walked to find common
    overlaps. Exhausting any input terminates the intersection.
    """
    return _range_intersection(*a)


def _range_intersection(*a: Iterable[_Span]) -> Iterator[_Span]:
    head: list[StoredIter[_Span]] = [StoredIter(range_coalesce(ax)) for ax in a]
    if not head:
        return
    try:
        ra, rl = head[0].stored
    except StopIteration:
        return
    while True:
        found = True
        for ax in head:
            try:
                sa, sl = ax.stored
            except StopIteration:
                return
            while sa + sl <= ra:
                try:
                    sa, sl = ax.next
                except StopIteration:
                    return
            if rl is not None and ra + rl <= sa:
                ra, rl = sa, sl
                found = False
                break
            if ra < sa:
                if rl is None:
                    rl = sl
                else:
                    rl -= sa - ra
                ra = sa
            elif rl is None:
                rl = sl - (ra - sa)
            assert rl is not None
            if ra + rl > sa + sl:
                rl = sa + sl - ra
            if ra + rl <= ra:
                if sa < ra:
                    rl = sl + sa - ra
                else:
                    rl = sl
                ra = sa
                found = False
                break
        if found:
            assert rl is not None
            yield (ra, rl)
            ra += rl
            rl = None


def range_invert(ra: datetime, rl: timedelta, a: Iterable[_Span]) -> Iterator[_Span]:
    """Subtract sorted intervals ``a`` from ``[ra, ra+rl)``; yield the gaps.

    Args:
        ra: Start of the interval to subtract from.
        rl: Length of the interval to subtract from.
        a: Sorted ``(start, length)`` intervals to remove.

    Yields:
        The portions of ``[ra, ra+rl)`` not covered by any interval in ``a``.
    """
    for sa, sl in a:
        if sa > ra + rl:
            break  # rest of `a` is past the end; yield the remaining tail below
        if sa + sl <= ra:
            continue
        if sa > ra:
            yield ra, sa - ra
            rl -= sa - ra + sl
            ra = sa + sl
        else:
            clip = sl - (ra - sa)
            ra += clip
            rl -= clip
        if ra + rl <= ra:
            return
    yield ra, rl


class RangeMixin:
    """Mixin for entities that expose a ``_range(start, end, **k)`` generator.

    Convenience wrappers around :meth:`_range`, ported from the legacy
    ``rainman.utils.RangeMixin``. Subclasses override :meth:`_range` to
    yield ``(start, length)`` interval tuples; the helpers here default
    the window to "from now, for N days".
    """

    def _range(self, start: datetime, end: datetime, **k: Any) -> Iterator[_Span]:
        """Yield ``(start, length)`` intervals within ``[start, end)``.

        Override in subclasses.
        """
        raise NotImplementedError

    def range(
        self,
        start: datetime | None = None,
        days: int = 1,
        **k: Any,
    ) -> Iterator[_Span]:
        """Intervals over the next ``days`` days (from ``start``, default now)."""
        if start is None:
            start = now()
        end = start + timedelta(days)
        return self._range(start, end, **k)

    def list_range(self, **k: Any) -> str:
        """Pretty-print the first three intervals of :meth:`range`."""
        r = self.range(days=99, **k)
        res = ""
        i = 0
        try:
            while True:
                a, b = next(r)
                if res:
                    res += " ¦ "
                res += f"{a.isoformat()} {b}"
                i += 1
                if i >= 3:
                    res += " ¦ …"
                    break
            return res
        except StopIteration:
            return res
        except ValueError:
            return "‹Error›"
