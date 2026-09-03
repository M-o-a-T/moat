"""Scheduler engine: per-entity interval ports, generation, recalculation.

Pure compute + ORM I/O layered over the rain schema, ported from the
legacy ``rainman`` model ``_range()`` methods and the ``genschedule`` /
``recalculate`` management commands. The Django ORM / qbroker / rpyc
stack is replaced by SQLAlchemy queries against a caller-supplied
session (:class:`moat.db.util.Mgr`); the heapq-driven concurrency
algorithms port unchanged.

Conventions mirror :mod:`moat.db.rain.range`: every ``*_range`` function
yields (or returns an iterator of) half-open ``(start, length)``
intervals with ``start`` a :class:`~datetime.datetime` and ``length`` a
:class:`~datetime.timedelta`. Inputs are walked forward in time, so the
output is sorted — the algebra in :mod:`moat.db.rain.range` relies on
that.

The day-family walkers (:func:`daytime_range`, :func:`day_range`,
:func:`dayrange_range`, :func:`valve_group_range`,
:func:`valve_group_xrange`) only traverse loaded relationships and need
no session; the override/schedule query functions take the session
explicitly so they can ``SELECT`` the rows that constrain the window.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from heapq import heappop, heappush

from sqlalchemy import select

from moat.db.rain.model import (
    Controller,
    Day,
    DayRange,
    DayTime,
    EnvGroup,
    EnvItem,
    Feed,
    Group,
    GroupOverride,
    History,
    Level,
    Schedule,
    Site,
    Valve,
    ValveOverride,
)
from moat.db.rain.range import (
    StoredIter,
    range_intersection,
    range_invert,
    range_union,
)
from moat.util.times import now, time_until

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.db.util import Mgr

    from collections.abc import Callable, Iterator

#: A ``(start, length)`` interval.
_Span = tuple[datetime, timedelta]

#: Look-back for override/schedule queries — mirrors the legacy
#: ``start__gte=start-timedelta(1,0)`` filter so a row that began just
#: before the window (and still overlaps it) is considered.
_DAY: timedelta = timedelta(days=1)

#: Gap left after an already-scheduled run before the valve may restart,
#: matching the legacy ``s.end+timedelta(0,60)``.
_GAP: timedelta = timedelta(seconds=60)


def _u(dt: datetime) -> datetime:
    """Normalise a datetime to aware-UTC — the engine's internal form.

    SQLite strips ``tzinfo`` on load, so datetimes read back from the
    database are naive; the rain schema stores UTC wall-clock throughout
    (mirroring the legacy Django ``USE_TZ`` store), so naive values are
    interpreted as UTC. Aware inputs are converted to UTC. Everything the
    engine compares is then aware-UTC, and :func:`daytime_range` hands
    :func:`moat.util.times.time_until` an aware-UTC ``t_now`` so its
    arithmetic is independent of the host timezone.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


#: Extra slack added to a schedule's stop time when computing controller
#: / feed concurrency, so back-to-back runs on the same resource don't
#: collide. The legacy ``genschedule`` called ``valve.range(.., add=30)``.
_ADD: timedelta = timedelta(seconds=30)

#: Minimum watering worth scheduling (legacy ``want < 10`` seconds).
_MIN_WATER: timedelta = timedelta(seconds=10)

#: Tokeniser for :class:`DayTime.descr` — ``[+-]?\\d+`` then a word unit,
#: the word optionally standing alone (e.g. ``monday``). The number is
#: optional so a bare weekday parses; the legacy flattener kept only the
#: non-empty fragments, and so does :func:`_split_descr`.
_TIME_SPLIT = re.compile(r"([-+]?\d+)?\s*(\w+)(?:\s+|$)")


def _split_descr(descr: str) -> list[str]:
    """Tokenise a day-time ``descr`` for :func:`moat.util.times.time_until`.

    Args:
        descr: A human time expression such as ``"6h 30m"`` or ``"monday"``.

    Returns:
        The flat ``[num, unit, …]`` token list the parser consumes.
    """
    out: list[str] = []
    for num, word in _TIME_SPLIT.findall(descr):
        if num:
            out.append(num)
        if word:
            out.append(word)
    return out


# ---------------------------------------------------------------------------
# Day / day-time / day-range walkers (no session: relationships only)
# ---------------------------------------------------------------------------


def daytime_range(daytime: DayTime, start: datetime, end: datetime) -> Iterator[_Span]:
    """Yield the intervals when ``daytime.descr`` is true within ``[start, end)``.

    Ports the legacy ``DayTime._range``: repeatedly find the next match
    of the parsed expression, then the next moment it stops matching,
    and emit the span between them. The modern
    :func:`moat.util.times.time_until` is tz-aware, so — unlike the
    legacy ``make_naive``/``make_aware`` dance — datetimes stay aware
    throughout.

    A degenerate (empty/zero-width) match breaks the loop rather than
    spinning forever; the legacy code had no such guard and could hang
    on a descriptor that matches instantly.
    """
    txt = _split_descr(daytime.descr)
    cur = _u(start)
    end = _u(end)
    while cur < end:
        a = time_until(txt, t_now=cur, invert=False)
        b = time_until(txt, t_now=a, invert=True)
        if b is None:
            # legacy retried once; preserve the attempt before giving up
            b = time_until(txt, t_now=a, invert=True)
        if b is None or b <= a:
            break
        yield a, b - a
        cur = b


def day_range(day: Day, start: datetime, end: datetime) -> Iterator[_Span]:
    """Union of a :class:`moat.db.rain.model.Day`'s :class:`moat.db.rain.model.DayTime` spans."""
    return range_union(*(daytime_range(t, start, end) for t in day.times))


def dayrange_range(dayrange: DayRange, start: datetime, end: datetime) -> Iterator[_Span]:
    """Intersection of a :class:`moat.db.rain.model.DayRange`'s day unions.

    A day-range with no days vacuously imposes no restriction, so the
    whole window is yielded. (The legacy ``DayRange._range`` crashed on
    ``range_intersection()`` with no arguments; the universe semantics
    belong here, not in the algebra — ``test_range.py`` pins
    ``range_intersection()`` to empty.)
    """
    days = list(dayrange.days)
    if not days:
        start, end = _u(start), _u(end)
        yield start, end - start
        return
    yield from range_intersection(*(day_range(d, start, end) for d in days))


# ---------------------------------------------------------------------------
# Group windows
# ---------------------------------------------------------------------------


def group_days_range(group: Group, start: datetime, end: datetime) -> Iterator[_Span]:
    """Union of all allowed day-ranges linked to ``group``."""
    return range_union(*(dayrange_range(dr, start, end) for dr in group.days))


def group_no_xdays_range(group: Group, start: datetime, end: datetime) -> Iterator[_Span]:
    """The complement of the union of ``group``'s excluded day-ranges."""
    start, end = _u(start), _u(end)
    blocked = range_union(*(dayrange_range(dr, start, end) for dr in group.xdays))
    return range_invert(start, end - start, blocked)


def group_not_blocked_range(
    sess: Mgr, group: Group, start: datetime, end: datetime
) -> Iterator[_Span]:
    """Yield the parts of ``[start, end)`` not covered by ``group``'s disallowing overrides.

    Args:
        sess: The owning session (for the override query).
        group: The group whose ``allowed=False`` overrides block the window.
        start: Window start.
        end: Window end.
    """
    start, end = _u(start), _u(end)
    cur = start
    stmt = (
        select(GroupOverride)
        .where(
            GroupOverride.group == group,
            GroupOverride.allowed.is_(False),
            GroupOverride.start >= start - _DAY,
            GroupOverride.start < end,
        )
        .order_by(GroupOverride.start)
    )
    for ov in sess.scalars(stmt):
        ov_start, ov_end = _u(ov.start), _u(ov.end)
        if ov_end <= cur:
            continue
        if ov_start > cur:
            yield cur, ov_start - cur
        cur = ov_end
    if end > cur:
        yield cur, end - cur


def group_allowed_range(
    sess: Mgr, group: Group, start: datetime, end: datetime
) -> Iterator[_Span]:
    """Yield the windows ``group``'s allowing overrides open up.

    An override straddling ``start`` contributes ``[start, ov.end)``;
    one wholly inside the window contributes ``[ov.start, ov.start+duration)``.
    """
    start, end = _u(start), _u(end)
    cur = start
    stmt = (
        select(GroupOverride)
        .where(
            GroupOverride.group == group,
            GroupOverride.allowed.is_(True),
            GroupOverride.start >= start - _DAY,
            GroupOverride.start < end,
        )
        .order_by(GroupOverride.start)
    )
    for ov in sess.scalars(stmt):
        ov_start, ov_end = _u(ov.start), _u(ov.end)
        if ov_end <= cur:
            continue
        if ov_start >= cur:
            yield ov_start, ov.duration_td
        else:
            yield cur, ov_end - cur
        cur = ov_end


def group_range(sess: Mgr, group: Group, start: datetime, end: datetime) -> Iterator[_Span]:
    """The full permitted window for ``group``: days ∩ ¬xdays, widened by
    allowing overrides, narrowed by disallowing ones.

    The legacy ``Group._range`` skipped the allowed-union when the group
    had no overrides at all; that optimisation is unnecessary because
    :func:`group_allowed_range` simply yields nothing for a group with no
    allowing overrides, and ``range_union(r, ∅) ≡ r``.
    """
    r: Iterator[_Span] = range_intersection(
        group_days_range(group, start, end),
        group_no_xdays_range(group, start, end),
    )
    r = range_union(r, group_allowed_range(sess, group, start, end))
    r = range_intersection(r, group_not_blocked_range(sess, group, start, end))
    return r


# ---------------------------------------------------------------------------
# Valve windows
# ---------------------------------------------------------------------------


def valve_group_range(valve: Valve, start: datetime, end: datetime) -> Iterator[_Span]:
    """Union of every day-range of every group ``valve`` belongs to."""
    spans = (dayrange_range(gd, start, end) for g in valve.groups for gd in g.days)
    return range_union(*spans)


def valve_group_xrange(valve: Valve, start: datetime, end: datetime) -> Iterator[_Span]:
    """Complement of the union of every excluded day-range of ``valve``'s groups."""
    start, end = _u(start), _u(end)
    spans = (dayrange_range(gd, start, end) for g in valve.groups for gd in g.xdays)
    return range_invert(start, end - start, range_union(*spans))


def valve_not_blocked_range(
    sess: Mgr, valve: Valve, start: datetime, end: datetime
) -> Iterator[_Span]:
    """Parts of ``[start, end)`` not blocked by ``valve``'s off (``running=False``) overrides."""
    start, end = _u(start), _u(end)
    cur = start
    stmt = (
        select(ValveOverride)
        .where(
            ValveOverride.valve == valve,
            ValveOverride.running.is_(False),
            ValveOverride.start >= start - _DAY,
            ValveOverride.start < end,
        )
        .order_by(ValveOverride.start)
    )
    for ov in sess.scalars(stmt):
        ov_start, ov_end = _u(ov.start), _u(ov.end)
        if ov_end <= cur:
            continue
        if ov_start > cur:
            yield cur, ov_start - cur
        cur = ov_end
    if end > cur:
        yield cur, end - cur


def valve_forced_range(sess: Mgr, valve: Valve, start: datetime, end: datetime) -> Iterator[_Span]:
    """The force-on (``running=True``) windows of ``valve``.

    Only the override windows themselves are yielded (not the gaps
    between them), so intersecting with this restricts scheduling to
    force-on times. An override that began before ``start`` contributes
    nothing — matching the legacy ``_forced_range`` quirk.
    """
    start, end = _u(start), _u(end)
    cur = start
    stmt = (
        select(ValveOverride)
        .where(
            ValveOverride.valve == valve,
            ValveOverride.running.is_(True),
            ValveOverride.start >= start - _DAY,
            ValveOverride.start < end,
        )
        .order_by(ValveOverride.start)
    )
    for ov in sess.scalars(stmt):
        ov_start, ov_end = _u(ov.start), _u(ov.end)
        if ov_end <= cur:
            continue
        if ov_start > cur:
            yield ov_start, ov.duration_td
        cur = ov_end


def valve_not_scheduled(
    sess: Mgr, valve: Valve, start: datetime, end: datetime
) -> Iterator[_Span]:
    """Parts of ``[start, end)`` free of existing schedules (with a post-run gap)."""
    start, end = _u(start), _u(end)
    cur = start
    stmt = (
        select(Schedule)
        .where(
            Schedule.valve == valve,
            Schedule.start >= start - _DAY,
            Schedule.start < end,
        )
        .order_by(Schedule.start)
    )
    for s in sess.scalars(stmt):
        s_start, s_end = _u(s.start), _u(s.end)
        if s_end <= cur:
            continue
        if s_start > cur:
            yield cur, s_start - cur
        cur = s_end + _GAP
    if end > cur:
        yield cur, end - cur


def controller_range(
    sess: Mgr,
    controller: Controller,
    start: datetime,
    end: datetime,
    add: timedelta = timedelta(0),
) -> Iterator[_Span]:
    """Times when ``controller`` can open another valve.

    Limits by ``max_on`` concurrent valves using a heap of stop-times
    over the controller's existing schedules. Ports the legacy
    ``Controller._range`` verbatim (the ``add`` slack extends each
    stop so back-to-back runs don't overbook).
    """
    start, end = _u(start), _u(end)
    cur = start
    stops: list[datetime] = []
    n_open = 0
    stmt = (
        select(Schedule)
        .join(Valve)
        .where(
            Valve.controller == controller,
            Schedule.start < end,
            Schedule.start >= start - _DAY,
        )
        .order_by(Schedule.start)
    )
    for s in sess.scalars(stmt):
        s_start, s_end = _u(s.start), _u(s.end)
        if s_end <= cur:
            continue
        while stops and stops[0] < s_start:
            if n_open == controller.max_on:
                cur = stops[0]
            heappop(stops)
            n_open -= 1
        n_open += 1
        heappush(stops, s_end + add)
        if n_open == controller.max_on and cur < s_start:
            yield cur, s_start - cur
    while n_open >= controller.max_on and stops:
        n_open -= 1
        cur = heappop(stops)
    if end > cur:
        yield cur, end - cur


def feed_range(
    sess: Mgr,
    feed: Feed,
    start: datetime,
    end: datetime,
    plusflow: float,
    add: timedelta = timedelta(0),
) -> Iterator[_Span]:
    """Times when ``feed`` can supply an additional ``plusflow`` litres/sec.

    Limits by the feed's flow capacity using a heap of ``(stop, dflow)``
    over the feed's existing schedules. Ports the legacy ``Feed._range``;
    ``flow is None`` selects single-valve mode (capacity tracked by
    count, not by litres).
    """
    start, end = _u(start), _u(end)
    cur = start
    stops: list[tuple[datetime, float]] = []
    if (
        feed.flow is None
    ):  # pragma: no cover — the schema (Feed.flow default+server_default) never stores NULL
        flow: float | None = None
    else:
        flow = feed.flow - plusflow
        if flow < 0:
            flow = None  # over-demand: this valve alone exceeds the feed → single-valve mode
    stmt = (
        select(Schedule)
        .join(Valve)
        .where(
            Valve.feed == feed,
            Schedule.start < end,
            Schedule.start >= start - _DAY,
        )
        .order_by(Schedule.start)
    )
    for s in sess.scalars(stmt):
        s_start, s_end = _u(s.start), _u(s.end)
        if s_end <= cur:
            continue
        while stops and stops[0][0] < s_start:
            if flow is None:
                nflow: float | None = None
                cond = len(stops) == 1
            else:
                nflow = flow + stops[0][1]
                cond = flow < 0 and nflow > 0
            if cond:
                cur = stops[0][0]
            flow = nflow
            heappop(stops)
        dflow = s.valve.flow
        heappush(stops, (s_end + add, dflow))
        if flow is not None:
            oflow = flow
            flow -= dflow
            cond = flow < 0 and oflow > 0
        else:
            cond = len(stops) == 1
        if cond and cur < s_start:
            yield cur, s_start - cur
    while stops and (flow < 0 if flow is not None else True):
        cur = stops[0][0]
        if flow is not None:
            flow += stops[0][1]
        heappop(stops)
    if end > cur:
        yield cur, end - cur


def valve_range(
    sess: Mgr,
    valve: Valve,
    start: datetime,
    end: datetime,
    *,
    forced: bool = False,
    add: timedelta = timedelta(0),
) -> Iterator[_Span]:
    """The orchestrator: every constraint on when ``valve`` may run.

    In normal mode the group day-windows (and their exclusions) are
    intersected, widened by each group's allowing overrides, narrowed by
    each group's disallowing overrides and the valve's own off overrides.
    In ``forced`` mode only the valve's force-on windows survive. Either
    way, already-scheduled times, controller capacity, and feed capacity
    are intersected in last.

    Args:
        sess: The owning session.
        valve: The valve to schedule.
        start: Window start.
        end: Window end.
        forced: Restrict to force-on override windows.
        add: Slack forwarded to the controller/feed capacity checks.
    """
    start, end = _u(start), _u(end)
    if forced:
        r: list[Iterator[_Span]] = [valve_forced_range(sess, valve, start, end)]
    else:
        r = [
            range_intersection(
                valve_group_range(valve, start, end),
                valve_group_xrange(valve, start, end),
            )
        ]
        for g in valve.groups:
            r.append(group_allowed_range(sess, g, start, end))
        r = [range_union(*r)]
        for g in valve.groups:
            r.append(group_not_blocked_range(sess, g, start, end))
        r.append(valve_not_blocked_range(sess, valve, start, end))
    r.append(valve_not_scheduled(sess, valve, start, end))
    r.append(controller_range(sess, valve.controller, start, end, add=add))
    r.append(feed_range(sess, valve.feed, start, end, valve.flow, add=add))
    return range_intersection(*r)


# ---------------------------------------------------------------------------
# Environmental factor (ported from rainman/models/env.py)
# ---------------------------------------------------------------------------


class _EnvCalc:
    """Cached environmental-factor calculator for one :class:`EnvGroup`.

    Loads the group's :class:`EnvItem` rows once and caches the
    null-ness-filtered subsets keyed by the ``(temp, wind, sun)`` usage
    triple, mirroring the legacy ``env_cache``. The weighted
    nearest-neighbour interpolation and the geometric combination of the
    seven usage triples port verbatim from ``EnvGroup.env_factor``.
    """

    #: ``(weight, (use_temp, use_wind, use_sun))`` — the seven combinations
    #: tried in order, weighted into the geometric mean.
    _COMBOS: tuple[tuple[int, tuple[bool, bool, bool]], ...] = (
        (6, (True, True, True)),
        (4, (False, True, True)),
        (4, (True, False, True)),
        (4, (True, True, False)),
        (1, (True, False, False)),
        (1, (False, True, False)),
        (1, (False, False, True)),
    )

    def __init__(self, eg: EnvGroup) -> None:
        self._eg = eg
        self._items: list[EnvItem] = list(eg.items)
        self._cache: dict[tuple[bool, bool, bool], list[EnvItem]] = {}

    def _factor_one(self, tws: tuple[bool, bool, bool], h: History) -> float | None:
        """Weighted-average factor for one usage triple, or ``None`` if unusable."""
        qtemp, qwind, qsun = tws
        if qtemp and h.temp is None:
            return None
        if qwind and h.wind is None:
            return None
        if qsun and h.sun is None:
            return None
        try:
            ec = self._cache[tws]
        except KeyError:
            ec = [
                it
                for it in self._items
                if (it.temp is None) == (not qtemp)
                and (it.wind is None) == (not qwind)
                and (it.sun is None) == (not qsun)
            ]
            self._cache[tws] = ec
        sum_f = 0.0
        sum_w = 0.0
        for ef in ec:
            d = 0.0
            if qtemp:
                assert h.temp is not None
                assert ef.temp is not None
                d += (h.temp - ef.temp) ** 2
            if qwind:
                assert h.wind is not None
                assert ef.wind is not None
                d += (h.wind - ef.wind) ** 2
            if qsun:
                assert h.sun is not None
                assert ef.sun is not None
                d += (h.sun - ef.sun) ** 2
            d = d ** (4 * 0.5)  # p=4: inverse-square weighting, favouring neighbours
            if d < 0.001:  # close enough to an exact datapoint
                return ef.factor
            sum_f += ef.factor / d
            sum_w += 1 / d
        if not sum_w:
            return None
        return sum_f / sum_w

    def env_factor(self, h: History) -> float:
        """Geometric combination of the seven usage-triple factors.

        With no matching data the result is ``1.0`` (the legacy neutral
        baseline: ``sum_f`` and ``sum_w`` both start at 1).
        """
        sum_f = 1.0
        sum_w = 1
        n = 1
        for weight, tws in self._COMBOS:
            f = self._factor_one(tws, h)
            if f is not None:
                sum_f *= f**weight
                sum_w += weight
                n += 1
        return sum_f ** (n / sum_w)


# ---------------------------------------------------------------------------
# Recalculation (ports rainman/management/commands/recalculate.py)
# ---------------------------------------------------------------------------


def _select_valves(
    sess: Mgr,
    *,
    site: str | None,
    controller: str | None,
    valve: str | None,
    order: str | None,
) -> list[Valve]:
    """Select valves by site / controller / valve-name filters.

    Args:
        sess: The owning session.
        site: Site name filter, or ``None`` for all sites.
        controller: Controller name filter (within the site if given).
        valve: Valve name filter.
        order: Column name to order by (e.g. ``"level"`` for generation),
            or ``None`` for insertion order.

    Returns:
        The matching :class:`Valve` rows, materialised so callers may
        insert schedules while iterating without invalidating the result.
    """
    stmt = select(Valve)
    if site is not None or controller is not None:
        stmt = stmt.join(Valve.controller)
    if site is not None:
        stmt = stmt.join(Controller.site).where(Site.name == site)
    if controller is not None:
        stmt = stmt.where(Controller.name == controller)
    if valve is not None:
        stmt = stmt.where(Valve.name == valve)
    if order is not None:
        stmt = stmt.order_by(getattr(Valve, order))
    return list(sess.scalars(stmt))


def recalculate(
    sess: Mgr,
    *,
    site: str | None = None,
    controller: str | None = None,
    valve: str | None = None,
    age: timedelta | None = None,
    save: bool = True,
    log: Callable[[str], None] | None = None,
) -> dict[str, int]:
    """Rebuild :class:`moat.db.rain.model.Level` rows from :class:`moat.db.rain.model.History`.

    Starts from the latest forced level in range (or, failing that, the
    earliest level — promoted to forced) and walks forward, applying
    evaporation (``site.rate · shade · envgroup.factor · env_factor ·
    adj · dt``), rain runoff, and delivered flow, clamping at
    ``max_level`` and zero. Forced levels are respected as anchors and
    left untouched. Finally the valve's headline ``level`` is updated.

    Args:
        sess: The owning session.
        site: Site name filter.
        controller: Controller name filter.
        valve: Valve name filter.
        age: Replay from this far back; ``None`` starts from the latest
            forced level (or earliest level) onward.
        save: Persist corrections to the levels and the valve.
        log: Optional event sink (e.g. per-valve corrections).

    Returns:
        ``{"valves": n, "updated": m}`` — valves processed and levels
        rewritten.
    """
    n = _u(now())
    updated = 0
    valves = 0
    for v in _select_valves(sess, site=site, controller=controller, valve=valve, order=None):
        valves += 1
        site_obj = v.controller.site
        envcalc = _EnvCalc(v.envgroup)
        start: datetime | None = None if age is None else n - age

        forced_stmt = select(Level).where(Level.valve == v, Level.forced.is_(True))
        if start is not None:
            forced_stmt = forced_stmt.where(Level.time >= start)
        forced_stmt = forced_stmt.order_by(Level.time.desc()).limit(1)
        last_fixed = sess.scalars(forced_stmt).first()
        if last_fixed is not None:
            lf_time = _u(last_fixed.time)
            if start is None or start < lf_time:
                start = lf_time
        else:
            earl_stmt = select(Level).where(Level.valve == v)
            if start is not None:
                earl_stmt = earl_stmt.where(Level.time >= start)
            earl_stmt = earl_stmt.order_by(Level.time.asc()).limit(1)
            earl = sess.scalars(earl_stmt).first()
            if earl is not None:
                earl.forced = True
                if save:
                    sess.flush()
                start = _u(earl.time)

        if start is None:
            hist: StoredIter[History] | None = None
        else:
            hist_stmt = (
                select(History)
                .where(History.site == site_obj, History.time >= start)
                .order_by(History.time.asc())
            )
            hist = StoredIter(sess.scalars(hist_stmt))

        level: float | None = None
        ts: datetime | None = None
        lvl_stmt = select(Level).where(Level.valve == v)
        if start is not None:
            lvl_stmt = lvl_stmt.where(Level.time >= start)
        lvl_stmt = lvl_stmt.order_by(Level.time.asc())
        for lv in sess.scalars(lvl_stmt):
            lv_time = _u(lv.time)
            if level is None or lv.forced:
                # anchor: drain history up to this level, then adopt it
                while hist is not None:
                    try:
                        if _u(hist.stored.time) > lv_time:
                            break
                        _ = hist.next
                    except StopIteration:
                        hist = None
                        break
                level = lv.level
                ts = lv_time
                continue
            assert ts is not None
            sum_f = 0.0
            sum_r = 0.0
            while hist is not None:
                h = hist.stored
                h_time = _u(h.time)
                if h_time > lv_time:
                    break
                try:
                    _ = hist.next
                except StopIteration:
                    hist = None
                f = envcalc.env_factor(h) * v.adj
                add_f = (
                    site_obj.rate
                    * v.shade
                    * (v.envgroup.factor * f)
                    * (h_time - ts).total_seconds()
                )
                add_r = v.runoff * h.rain
                sum_f += add_f
                sum_r += add_r
                ts = h_time
            level += sum_f
            if (lv.flow > 0 or sum_r > 0) and level > v.max_level:
                level = v.max_level
            level -= sum_r + lv.flow / v.area
            if sum_r == 0 and lv.flow == 0 and level < 0:
                level = 0
            if abs(lv.level - level) > (abs(lv.level) + abs(level)) / 100:
                if log is not None:
                    log(f"Updated {v.controller.name}:{v.name} {lv.level} → {level}")
                if save:
                    lv.level = level
                    updated += 1
        if level is not None and abs(v.level - level) > (abs(v.level) + abs(level)) / 100:
            if log is not None:
                log(f"Updated valve {v.controller.name}:{v.name} {v.level} → {level}")
            if save:
                v.level = level
        if save:
            sess.flush()
    return {"valves": valves, "updated": updated}


# ---------------------------------------------------------------------------
# Generation (ports rainman/management/commands/genschedule.py)
# ---------------------------------------------------------------------------


def _watering_time(v: Valve, level: float | None = None) -> timedelta:
    """Seconds of run time to lower ``level`` to ``stop_level``.

    ``watering_time = (level - stop_level) · area / flow``, truncated to
    whole seconds (legacy ``int(res)``).
    """
    if level is None:
        level = v.start_level
    return timedelta(seconds=int((level - v.stop_level) * v.area / v.flow))


def _force_valve(
    sess: Mgr,
    v: Valve,
    soon: datetime,
    horizon_end: datetime,
    *,
    save: bool,
    log: Callable[[str], None] | None,
) -> int:
    """Emit forced schedules for ``v``'s force-on overrides. Returns the count."""
    count = 0
    for a, b in valve_range(sess, v, soon, horizon_end, forced=True):
        if log is not None:
            log(f"Forced {v.controller.name}:{v.name} @ {a} for {b}")
        if save:
            sess.add(Schedule(valve=v, start=a, duration=int(b.total_seconds()), forced=True))
            count += 1
    if save and count:
        sess.flush()
    return count


def _gen_valve(
    sess: Mgr,
    v: Valve,
    n: datetime,
    soon: datetime,
    horizon_end: datetime,
    *,
    save: bool,
    log: Callable[[str], None] | None,
) -> int:
    """Plan watering slots for ``v`` until its level deficit is met. Returns schedules added."""
    need = v.stop_level if v.priority else v.start_level
    if v.level < need:
        if log is not None:
            log(f"{v.controller.name}:{v.name}: nothing to do (has {v.level}, need {need})")
        return 0
    level = min(v.level, v.max_level)
    want = _watering_time(v, level)
    has = timedelta(0)
    last_end: datetime | None = None
    stmt = (
        select(Schedule)
        .where(Schedule.valve == v, Schedule.start >= soon - _DAY)
        .order_by(Schedule.start)
    )
    for s in sess.scalars(stmt):
        s_end = _u(s.end)
        last_end = s_end
        if s_end < n:
            continue
        has += s.duration_td
    if last_end is not None and v.min_delay_td is not None:
        last_end = last_end + v.min_delay_td

    if has:
        if save:
            v.priority = want > has * 1.2
        if log is not None:
            log(f"{v.controller.name}:{v.name}: already scheduled (has {has}, want {want})")
        return 0
    if want < _MIN_WATER:
        if save:
            v.priority = False
        if log is not None:
            log(f"{v.controller.name}:{v.name}: too little to do ({want})")
        return 0

    added = 0
    for slot_start, slot_len in valve_range(sess, v, soon, horizon_end, add=_ADD):
        a, b = slot_start, slot_len
        if a > soon:
            break  # defer the rest to the next run
        if last_end is not None and last_end > a:
            if last_end >= a + b:
                continue
            b -= last_end - a
            a = last_end
            last_end = None
        if b < want / 5:
            if log is not None:
                log(f"{v.controller.name}:{v.name}: slot too short @ {a} ({b})")
            continue
        mr = v.max_run_td
        if mr is not None and b > mr:
            b = mr
        if b < want:
            if log is not None:
                log(f"{v.controller.name}:{v.name}: partial @ {a} for {b} of {want}")
            if save:
                sess.add(Schedule(valve=v, start=a, duration=int(b.total_seconds())))
                added += 1
                v.priority = True
            want -= b
            break
        if log is not None:
            log(f"{v.controller.name}:{v.name}: total @ {a} for {want}")
        if save:
            sess.add(Schedule(valve=v, start=a, duration=int(want.total_seconds())))
            added += 1
            v.priority = False
        want = None
        break
    else:
        if want is not None and log is not None:
            log(f"{v.controller.name}:{v.name}: missing {want}")
    if save and added:
        sess.flush()
    return added


def generate_schedule(
    sess: Mgr,
    *,
    site: str | None = None,
    controller: str | None = None,
    valve: str | None = None,
    start: datetime | None = None,
    horizon: timedelta = timedelta(days=1),
    delay: timedelta = timedelta(minutes=10),
    save: bool = True,
    log: Callable[[str], None] | None = None,
) -> dict[str, int]:
    """Generate schedules for the matching valves.

    For each valve (driest first — ordered by ``level``) first emits any
    forced (force-on) schedules, then plans watering slots within
    ``[start+delay, start+delay+horizon)`` until the valve's level
    deficit is met, honouring ``max_run`` / ``min_delay`` and skipping
    valves whose feed is disabled.

    Args:
        sess: The owning session.
        site: Site name filter.
        controller: Controller name filter.
        valve: Valve name filter.
        start: Plan from this moment (default: now).
        horizon: How far ahead to plan.
        delay: Offset from ``start`` before planning begins.
        save: Insert the computed :class:`moat.db.rain.model.Schedule` rows.
        log: Optional event sink.

    Returns:
        ``{"valves": n, "schedules": s, "forced": f}`` — valves visited,
        ordinary schedules added, and forced schedules added.
    """
    n = _u(now() if start is None else start)
    soon = n + delay
    horizon_end = soon + horizon
    valves = 0
    schedules = 0
    forced = 0
    for v in _select_valves(sess, site=site, controller=controller, valve=valve, order="level"):
        valves += 1
        if v.feed.disabled:
            continue
        forced += _force_valve(sess, v, soon, horizon_end, save=save, log=log)
        schedules += _gen_valve(sess, v, n, soon, horizon_end, save=save, log=log)
    return {"valves": valves, "schedules": schedules, "forced": forced}
