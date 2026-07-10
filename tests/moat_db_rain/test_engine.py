"""Tests for the rain scheduler engine (Phase 8).

Exercises :mod:`moat.db.rain.engine` — the per-entity ``*_range`` ports,
:func:`generate_schedule`, :func:`recalculate`, and the
:class:`_EnvCalc` environmental-factor interpolation — against a temp
SQLite database seeded via the ORM.

The engine normalises datetimes to naive-UTC internally (SQLite strips
``tzinfo`` on load); tests therefore pass **aware-UTC** inputs and assert
**naive-UTC** outputs, keeping the suite independent of the host
timezone. :func:`moat.util.times.time_until` is fed aware-UTC ``t_now``
so its arithmetic is fully determined by the test, not by ``localtime``.
"""

from __future__ import annotations

import pytest
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

import moat.db.util  # noqa: F401  — attaches the sqlite ``foreign_keys=ON`` pragma listener
from moat.util import ctx_as
from moat.db.rain import model as r
from moat.db.rain.engine import (
    _EnvCalc,
    _u,
    _watering_time,
    controller_range,
    day_range,
    dayrange_range,
    daytime_range,
    feed_range,
    generate_schedule,
    group_allowed_range,
    group_not_blocked_range,
    group_range,
    recalculate,
    valve_not_blocked_range,
    valve_not_scheduled,
    valve_range,
)
from moat.db.util import Mgr, session


def _n(year, month, day, hour=0, minute=0, second=0):
    """An aware-UTC datetime — the engine's output form.

    The engine normalises every datetime it yields or stores to aware-UTC
    (SQLite strips ``tzinfo`` on load, so naive DB values are read back as
    UTC); tests assert against aware-UTC values. The helper keeps the
    call sites terse without tripping the repo's ``DTZ001`` rule.
    """
    return datetime(year, month, day, hour, minute, second, tzinfo=UTC)


def _swallow(_msg: str) -> None:
    """A no-op sink for engine ``log`` callbacks, to exercise the narration branches."""


#: A tz-aware UTC anchor at 2025-01-01 06:00 — a clean match boundary for
#: the ``"6h"`` day-time descriptor (hour == 6).
T0 = datetime(2025, 1, 1, 6, 0, 0, tzinfo=UTC)


def _mgr(engine):
    """A ``(sess, mgr)`` pair bound to ``engine``, with the session ContextVar set."""
    sess_cm = Session(engine)
    sess = sess_cm.__enter__()
    ctx = ctx_as(session, Mgr(sess))
    ctx.__enter__()
    return sess, sess_cm, ctx


def _close(sess_cm, ctx):
    ctx.__exit__(None, None, None)
    sess_cm.__exit__(None, None, None)


def _seed(
    engine,
    *,
    max_on=2,
    feed_flow=100.0,
    disabled=False,
    valve_level=8.0,
    start_level=8.0,
    stop_level=3.0,
    max_level=10.0,
    max_run=None,
    flow=2.0,
    area=10.0,
):
    """Build the standard engine world: site, controller, feed, env, one valve.

    The valve belongs to a group whose day-range is a single ``Day`` with a
    ``DayTime`` of ``"6h"`` (the 06:00 hour, daily). Returns the persisted
    objects via a fresh session left open for the test.
    """
    sess, cm, ctx = _mgr(engine)
    site = r.Site(name="home")
    ctrl = r.Controller(name="C1", site=site, location="rack", max_on=max_on)
    feed = r.Feed(name="F1", site=site, flow=feed_flow, disabled=disabled)
    eg = r.EnvGroup(name="std", site=site, factor=1.0)
    v1 = r.Valve(
        name="V1",
        controller=ctrl,
        feed=feed,
        envgroup=eg,
        location="p",
        flow=flow,
        area=area,
        start_level=start_level,
        stop_level=stop_level,
        max_level=max_level,
        max_run=max_run,
        level=valve_level,
        shade=1.0,
        runoff=1.0,
    )
    day = r.Day(name="d6")
    r.DayTime(day=day, descr="6h")
    dr = r.DayRange(name="dr6")
    dr.days.add(day)
    g = r.Group(name="g1", site=site)
    g.days.add(dr)
    g.valves.add(v1)
    sess.add_all([site, ctrl, feed, eg, v1, day, dr, g])
    sess.flush()
    return sess, cm, ctx, dict(site=site, ctrl=ctrl, feed=feed, eg=eg, v1=v1, day=day, dr=dr, g=g)


# ---------------------------------------------------------------------------
# Day / day-time / day-range walkers
# ---------------------------------------------------------------------------


def test_daytime_range_daily_hour(engine):
    """``"6h"`` yields the 06:00–07:00 hour each day, as naive-UTC spans."""
    sess, cm, ctx = _mgr(engine)
    try:
        day = r.Day(name="d6")
        dt = r.DayTime(day=day, descr="6h")
        sess.add(day)
        sess.flush()
        spans = [
            (a, b)
            for a, b in daytime_range(dt, T0, T0 + timedelta(days=2, hours=1))
            if a < _n(2025, 1, 3, 6, 0)
        ]
        assert spans == [
            (_n(2025, 1, 1, 6, 0), timedelta(hours=1)),
            (_n(2025, 1, 2, 6, 0), timedelta(hours=1)),
        ]
    finally:
        _close(cm, ctx)


def test_day_range_unions_two_daytimes(engine):
    """``day_range`` coalesces each ``DayTime``'s spans (in-window ones kept)."""
    sess, cm, ctx = _mgr(engine)
    try:
        day = r.Day(name="twice")
        r.DayTime(day=day, descr="6h")
        r.DayTime(day=day, descr="18h")
        sess.add(day)
        sess.flush()
        end = _n(2025, 1, 1, 19, 0)
        spans = [(a, b) for a, b in day_range(day, T0, T0 + timedelta(hours=13)) if a < end]
        assert spans == [
            (_n(2025, 1, 1, 6, 0), timedelta(hours=1)),
            (_n(2025, 1, 1, 18, 0), timedelta(hours=1)),
        ]
    finally:
        _close(cm, ctx)


def test_dayrange_range_empty_is_whole_window(engine):
    """A day-range with no days imposes no restriction (universe semantics)."""
    sess, cm, ctx = _mgr(engine)
    try:
        dr = r.DayRange(name="empty")
        sess.add(dr)
        sess.flush()
        spans = list(dayrange_range(dr, T0, T0 + timedelta(hours=2)))
        assert spans == [(_n(2025, 1, 1, 6, 0), timedelta(hours=2))]
    finally:
        _close(cm, ctx)


def test_dayrange_range_intersects_days(engine):
    """A day-range is the intersection of its days' unions."""
    sess, cm, ctx = _mgr(engine)
    try:
        d6 = r.Day(name="d6")
        r.DayTime(day=d6, descr="6h")
        d18 = r.Day(name="d18")
        r.DayTime(day=d18, descr="18h")
        dr = r.DayRange(name="both")
        dr.days.add(d6)
        dr.days.add(d18)
        sess.add_all([d6, d18, dr])
        sess.flush()
        # intersection of the 06:00 hour and the 18:00 hour over a day is empty
        spans = list(dayrange_range(dr, T0, T0 + timedelta(days=1)))
        assert spans == []
    finally:
        _close(cm, ctx)


# ---------------------------------------------------------------------------
# Override / schedule query functions
# ---------------------------------------------------------------------------


def test_group_not_blocked_range(engine):
    """Disallowed group overrides carve their windows out of ``[start, end)``."""
    sess, cm, ctx, objs = _seed(engine)
    try:
        g = objs["g"]
        sess.add(
            r.GroupOverride(
                group=g,
                allowed=False,
                start=datetime(2025, 1, 1, 6, 30, tzinfo=UTC),
                duration=1800,
            )
        )
        # a wholly-past override (before the window) is skipped via the ``continue`` branch
        sess.add(
            r.GroupOverride(
                group=g,
                allowed=False,
                start=datetime(2025, 1, 1, 4, 0, tzinfo=UTC),
                duration=60,
            )
        )
        sess.flush()
        spans = list(
            group_not_blocked_range(
                Mgr(sess),
                g,
                datetime(2025, 1, 1, 6, 0, tzinfo=UTC),
                datetime(2025, 1, 1, 8, 0, tzinfo=UTC),
            )
        )
        assert spans == [
            (_n(2025, 1, 1, 6, 0), timedelta(minutes=30)),
            (_n(2025, 1, 1, 7, 0), timedelta(hours=1)),
        ]
    finally:
        _close(cm, ctx)


def test_group_allowed_range_straddles_start(engine):
    """An allowing override that began before ``start`` contributes ``[start, end)``."""
    sess, cm, ctx, objs = _seed(engine)
    try:
        g = objs["g"]
        sess.add(
            r.GroupOverride(
                group=g,
                allowed=True,
                start=datetime(2025, 1, 1, 5, 0, tzinfo=UTC),
                duration=3600,
            )
        )
        # a wholly-past allowing override is skipped via the ``continue`` branch
        sess.add(
            r.GroupOverride(
                group=g,
                allowed=True,
                start=datetime(2025, 1, 1, 3, 0, tzinfo=UTC),
                duration=60,
            )
        )
        sess.flush()
        spans = list(
            group_allowed_range(
                Mgr(sess),
                g,
                datetime(2025, 1, 1, 5, 30, tzinfo=UTC),
                datetime(2025, 1, 1, 7, 0, tzinfo=UTC),
            )
        )
        # override [05:00, 06:00) straddles the 05:30 start → yields [05:30, 06:00)
        assert spans == [(_n(2025, 1, 1, 5, 30), timedelta(minutes=30))]
    finally:
        _close(cm, ctx)


def test_valve_not_scheduled_leaves_gap(engine):
    """An existing schedule blocks its window plus a 60-second post-run gap."""
    sess, cm, ctx, objs = _seed(engine)
    try:
        v1 = objs["v1"]
        sess.add(r.Schedule(valve=v1, start=datetime(2025, 1, 1, 6, 0, tzinfo=UTC), duration=120))
        # a schedule starting after the window start yields the lead-in gap
        sess.add(r.Schedule(valve=v1, start=datetime(2025, 1, 1, 6, 4, tzinfo=UTC), duration=60))
        sess.flush()
        spans = list(
            valve_not_scheduled(
                Mgr(sess),
                v1,
                datetime(2025, 1, 1, 6, 0, tzinfo=UTC),
                datetime(2025, 1, 1, 6, 5, 0, tzinfo=UTC),
            )
        )
        # [06:00, 06:02) occupied → gap to 06:03; then [06:04, 06:05) occupied → free [06:03, 06:04)
        assert spans == [(_n(2025, 1, 1, 6, 3), timedelta(minutes=1))]
    finally:
        _close(cm, ctx)


# ---------------------------------------------------------------------------
# Controller / feed capacity (heap algorithms)
# ---------------------------------------------------------------------------


def test_controller_range_max_on_one(engine):
    """With ``max_on=1`` and one running schedule, the window opens at stop+add."""
    sess, cm, ctx, objs = _seed(engine, max_on=1)
    try:
        v1 = objs["v1"]
        ctrl = objs["ctrl"]
        sess.add(r.Schedule(valve=v1, start=datetime(2025, 1, 1, 6, 0, tzinfo=UTC), duration=25))
        sess.flush()
        spans = list(
            controller_range(
                Mgr(sess),
                ctrl,
                datetime(2025, 1, 1, 6, 0, tzinfo=UTC),
                datetime(2025, 1, 1, 8, 0, tzinfo=UTC),
                add=timedelta(seconds=30),
            )
        )
        # the running valve ends at 06:00:25; +30s slack → free from 06:00:55
        assert spans == [(_n(2025, 1, 1, 6, 0, 55), timedelta(hours=1, minutes=59, seconds=5))]
    finally:
        _close(cm, ctx)


def test_feed_range_capacity(engine):
    """A feed driven over capacity (flow < 0) frees up only as runs end."""
    sess, cm, ctx, objs = _seed(engine, feed_flow=3.0)
    try:
        feed = objs["feed"]
        v1 = objs["v1"]
        # one valve (flow=2) already drawing; asking for another 2 of a 3 l/s feed
        sess.add(r.Schedule(valve=v1, start=datetime(2025, 1, 1, 6, 0, tzinfo=UTC), duration=40))
        sess.flush()
        spans = list(
            feed_range(
                Mgr(sess),
                feed,
                datetime(2025, 1, 1, 6, 0, tzinfo=UTC),
                datetime(2025, 1, 1, 6, 2, 0, tzinfo=UTC),
                2.0,
                add=timedelta(seconds=30),
            )
        )
        # capacity 3 - 2 (running) - 2 (asked) = -1 → over → wait until 06:01:10 (40+30)
        assert spans[0][0] == _n(2025, 1, 1, 6, 1, 10)
    finally:
        _close(cm, ctx)


# ---------------------------------------------------------------------------
# valve_range (orchestrator)
# ---------------------------------------------------------------------------


def test_valve_range_off_override_blocks_inside_day_window(engine):
    """An off override inside the 06:00 hour splits it at the override start."""
    sess, cm, ctx, objs = _seed(engine)
    try:
        v1 = objs["v1"]
        sess.add(
            r.ValveOverride(
                valve=v1,
                running=False,
                start=datetime(2025, 1, 1, 6, 30, tzinfo=UTC),
                duration=1800,
            )
        )
        # a wholly-past off override is skipped via the ``continue`` branch
        sess.add(
            r.ValveOverride(
                valve=v1,
                running=False,
                start=datetime(2025, 1, 1, 4, 0, tzinfo=UTC),
                duration=60,
            )
        )
        sess.flush()
        spans = list(
            valve_range(
                Mgr(sess),
                v1,
                datetime(2025, 1, 1, 6, 0, tzinfo=UTC),
                datetime(2025, 1, 1, 7, 30, tzinfo=UTC),
            )
        )
        # 06:00 hour minus [06:30, 07:00) → just [06:00, 06:30)
        assert spans == [(_n(2025, 1, 1, 6, 0), timedelta(minutes=30))]
    finally:
        _close(cm, ctx)


def test_valve_range_forced_restricts_to_force_windows(engine):
    """Forced mode yields only the force-on override window (not the day window)."""
    sess, cm, ctx, objs = _seed(engine)
    try:
        v1 = objs["v1"]
        sess.add(
            r.ValveOverride(
                valve=v1,
                running=True,
                start=datetime(2025, 1, 1, 8, 0, tzinfo=UTC),
                duration=600,
            )
        )
        sess.flush()
        spans = list(
            valve_range(
                Mgr(sess),
                v1,
                datetime(2025, 1, 1, 6, 0, tzinfo=UTC),
                datetime(2025, 1, 1, 10, 0, tzinfo=UTC),
                forced=True,
            )
        )
        assert spans == [(_n(2025, 1, 1, 8, 0), timedelta(minutes=10))]
    finally:
        _close(cm, ctx)


# ---------------------------------------------------------------------------
# generate_schedule
# ---------------------------------------------------------------------------


def test_generate_schedule_basic(engine):
    """A dry valve gets one schedule at the window start for its watering time."""
    sess, cm, ctx, objs = _seed(engine, valve_level=8.0)
    try:
        mgr = Mgr(sess)
        res = generate_schedule(
            mgr, site="home", start=T0, delay=timedelta(0), horizon=timedelta(days=2), log=_swallow
        )
        assert res == {"valves": 1, "schedules": 1, "forced": 0}
        scheds = list(mgr.scalars(select(r.Schedule).order_by(r.Schedule.start)))
        assert len(scheds) == 1
        s = scheds[0]
        assert s.valve.name == "V1"
        assert _u(s.start) == T0
        # watering time = (8 - 3) * 10 / 2 = 25 s
        assert s.duration == 25
        assert s.forced is False
        assert objs["v1"].priority is False
    finally:
        _close(cm, ctx)


def test_generate_schedule_skips_disabled_feed(engine):
    """A valve whose feed is disabled is visited but never scheduled."""
    sess, cm, ctx, _ = _seed(engine, disabled=True, valve_level=8.0)
    try:
        mgr = Mgr(sess)
        res = generate_schedule(
            mgr, site="home", start=T0, delay=timedelta(0), horizon=timedelta(days=1)
        )
        assert res == {"valves": 1, "schedules": 0, "forced": 0}
        assert list(mgr.scalars(select(r.Schedule))) == []
    finally:
        _close(cm, ctx)


def test_generate_schedule_emits_forced(engine):
    """A force-on override produces a forced schedule; it also satisfies demand."""
    sess, cm, ctx, objs = _seed(engine, valve_level=8.0)
    try:
        mgr = Mgr(sess)
        v1 = objs["v1"]
        sess.add(
            r.ValveOverride(
                valve=v1,
                running=True,
                start=datetime(2025, 1, 1, 8, 0, tzinfo=UTC),
                duration=600,
            )
        )
        sess.flush()
        res = generate_schedule(
            mgr, site="home", start=T0, delay=timedelta(0), horizon=timedelta(days=1), log=_swallow
        )
        assert res == {"valves": 1, "schedules": 0, "forced": 1}
        scheds = list(mgr.scalars(select(r.Schedule).order_by(r.Schedule.start)))
        assert len(scheds) == 1
        assert _u(scheds[0].start) == _n(2025, 1, 1, 8, 0)
        assert scheds[0].duration == 600
        assert scheds[0].forced is True
    finally:
        _close(cm, ctx)


def test_generate_schedule_filters_by_controller_and_valve(engine):
    """The site/controller/valve name filters narrow the valve selection."""
    sess, cm, ctx, objs = _seed(engine)
    try:
        mgr = Mgr(sess)
        ctrl = objs["ctrl"]
        eg = objs["eg"]
        feed = objs["feed"]
        # a second valve on the same controller, in the same group
        v2 = r.Valve(
            name="V2",
            controller=ctrl,
            feed=feed,
            envgroup=eg,
            location="q",
            flow=2.0,
            area=10.0,
            start_level=8.0,
            stop_level=3.0,
            max_level=10.0,
            level=8.0,
        )
        objs["g"].valves.add(v2)
        sess.add(v2)
        sess.flush()
        res = generate_schedule(
            mgr, site="home", valve="V2", start=T0, delay=timedelta(0), horizon=timedelta(days=1)
        )
        assert res == {"valves": 1, "schedules": 1, "forced": 0}
        scheds = list(mgr.scalars(select(r.Schedule)))
        assert len(scheds) == 1
        assert scheds[0].valve.name == "V2"
    finally:
        _close(cm, ctx)


# ---------------------------------------------------------------------------
# recalculate
# ---------------------------------------------------------------------------


def _seed_recalc(engine):
    """A site + valve (no groups, so ``adj == 1.0``) with the default 10 mm/day rate."""
    sess, cm, ctx = _mgr(engine)
    site = r.Site(name="home")  # rate = 10/86400 mm/s (default)
    ctrl = r.Controller(name="C1", site=site, location="rack")
    feed = r.Feed(name="F1", site=site, flow=100.0)
    eg = r.EnvGroup(name="std", site=site, factor=1.0)  # no items → env_factor 1.0
    v = r.Valve(
        name="V1",
        controller=ctrl,
        feed=feed,
        envgroup=eg,
        location="p",
        flow=2.0,
        area=10.0,
        start_level=8.0,
        stop_level=3.0,
        max_level=10.0,
        level=5.0,
        shade=1.0,
        runoff=1.0,
    )
    sess.add_all([site, ctrl, feed, eg, v])
    sess.flush()
    return sess, cm, ctx, dict(site=site, v=v)


def test_recalculate_evaporation_from_forced_anchor(engine):
    """Evaporation raises the dryness level by ``rate·shade·factor·dt``."""
    sess, cm, ctx, objs = _seed_recalc(engine)
    try:
        mgr = Mgr(sess)
        v = objs["v"]
        site = objs["site"]
        l0 = datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC)
        l1 = datetime(2025, 1, 1, 1, 0, 0, tzinfo=UTC)
        h = datetime(2025, 1, 1, 0, 30, 0, tzinfo=UTC)
        sess.add(r.Level(valve=v, time=l0, level=5.0, forced=True))
        sess.add(r.Level(valve=v, time=l1, level=5.0, forced=False))
        sess.add(r.History(site=site, time=h, rain=0.0))
        # a history row before the forced anchor is drained (consume + break) during the anchor reset
        sess.add(r.History(site=site, time=datetime(2024, 12, 31, 23, 0, tzinfo=UTC), rain=0.0))
        sess.flush()
        res = recalculate(mgr, site="home", log=_swallow)
        assert res == {"valves": 1, "updated": 1}
        levels = list(mgr.scalars(select(r.Level).order_by(r.Level.time)))
        assert levels[0].level == 5.0  # forced anchor untouched
        # evap = 10/86400 mm/s * 1800 s = 0.20833…
        assert levels[1].level == pytest.approx(5.0 + 10 / 86400 * 1800)
        assert v.level == pytest.approx(5.0 + 10 / 86400 * 1800)
    finally:
        _close(cm, ctx)


def test_recalculate_rain_reduces_dryness(engine):
    """Rain runoff lowers the dryness level by ``runoff·rain``."""
    sess, cm, ctx, objs = _seed_recalc(engine)
    try:
        mgr = Mgr(sess)
        v = objs["v"]
        site = objs["site"]
        l0 = datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC)
        l1 = datetime(2025, 1, 1, 1, 0, 0, tzinfo=UTC)
        h = datetime(2025, 1, 1, 0, 30, 0, tzinfo=UTC)
        sess.add(r.Level(valve=v, time=l0, level=5.0, forced=True))
        sess.add(r.Level(valve=v, time=l1, level=5.0, forced=False))
        sess.add(r.History(site=site, time=h, rain=2.0))
        sess.flush()
        recalculate(mgr, site="home", log=_swallow)
        levels = list(mgr.scalars(select(r.Level).order_by(r.Level.time)))
        # level = 5 + evap(0.20833) - runoff·rain(2.0) = 3.20833…
        assert levels[1].level == pytest.approx(5.0 + 10 / 86400 * 1800 - 2.0)
    finally:
        _close(cm, ctx)


def test_recalculate_watering_reduces_dryness(engine):
    """Delivered flow lowers the dryness level by ``flow/area`` (mm)."""
    sess, cm, ctx, objs = _seed_recalc(engine)
    try:
        mgr = Mgr(sess)
        v = objs["v"]
        site = objs["site"]
        l0 = datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC)
        l1 = datetime(2025, 1, 1, 1, 0, 0, tzinfo=UTC)
        h = datetime(2025, 1, 1, 0, 30, 0, tzinfo=UTC)
        sess.add(r.Level(valve=v, time=l0, level=5.0, forced=True))
        sess.add(r.Level(valve=v, time=l1, level=5.0, forced=False, flow=20.0))
        sess.add(r.History(site=site, time=h, rain=0.0))
        sess.flush()
        recalculate(mgr, site="home", log=_swallow)
        levels = list(mgr.scalars(select(r.Level).order_by(r.Level.time)))
        # level = 5 + evap(0.20833) - flow/area(20/10=2.0) = 3.20833…
        assert levels[1].level == pytest.approx(5.0 + 10 / 86400 * 1800 - 20.0 / 10.0)
    finally:
        _close(cm, ctx)


def test_recalculate_promotes_earliest_level_when_no_forced(engine):
    """Without a forced anchor, the earliest level is promoted and used as the start."""
    sess, cm, ctx, objs = _seed_recalc(engine)
    try:
        mgr = Mgr(sess)
        v = objs["v"]
        site = objs["site"]
        l0 = datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC)
        l1 = datetime(2025, 1, 1, 1, 0, 0, tzinfo=UTC)
        h = datetime(2025, 1, 1, 0, 30, 0, tzinfo=UTC)
        sess.add(r.Level(valve=v, time=l0, level=5.0, forced=False))
        sess.add(r.Level(valve=v, time=l1, level=5.0, forced=False))
        sess.add(r.History(site=site, time=h, rain=0.0))
        sess.flush()
        recalculate(mgr, site="home")
        levels = list(mgr.scalars(select(r.Level).order_by(r.Level.time)))
        assert levels[0].forced is True  # promoted to anchor
        assert levels[0].level == 5.0  # anchor value adopted unchanged
        assert levels[1].level == pytest.approx(5.0 + 10 / 86400 * 1800)
    finally:
        _close(cm, ctx)


# ---------------------------------------------------------------------------
# _EnvCalc environmental-factor interpolation
# ---------------------------------------------------------------------------


def test_env_factor_no_items_is_neutral(engine):
    """An env group with no data points yields the neutral factor 1.0."""
    sess, cm, ctx = _mgr(engine)
    try:
        site = r.Site(name="home")
        eg = r.EnvGroup(name="std", site=site, factor=1.0)
        sess.add_all([site, eg])
        sess.flush()
        h = r.History(
            site=site, time=datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC), temp=20.0, wind=0.0, sun=0.0
        )
        sess.add(h)
        sess.flush()
        assert _EnvCalc(eg).env_factor(h) == 1.0
    finally:
        _close(cm, ctx)


def test_env_factor_inverse_distance_midpoint(engine):
    """Two temp-only points factor the midpoint by inverse-distance average."""
    sess, cm, ctx = _mgr(engine)
    try:
        site = r.Site(name="home")
        eg = r.EnvGroup(name="std", site=site, factor=1.0)
        r.EnvItem(group=eg, factor=1.0, temp=20.0)
        r.EnvItem(group=eg, factor=3.0, temp=22.0)
        sess.add_all([site, eg])
        sess.flush()
        h = r.History(site=site, time=datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC), temp=21.0)
        sess.add(h)
        sess.flush()
        # equidistant from both → (1.0 + 3.0) / 2 = 2.0
        assert _EnvCalc(eg).env_factor(h) == pytest.approx(2.0)
    finally:
        _close(cm, ctx)


def test_env_factor_exact_datapoint(engine):
    """A history row exactly matching a data point adopts that point's factor."""
    sess, cm, ctx = _mgr(engine)
    try:
        site = r.Site(name="home")
        eg = r.EnvGroup(name="std", site=site, factor=1.0)
        r.EnvItem(group=eg, factor=2.0, temp=20.0)
        r.EnvItem(group=eg, factor=3.0, temp=22.0)
        sess.add_all([site, eg])
        sess.flush()
        h = r.History(site=site, time=datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC), temp=20.0)
        sess.add(h)
        sess.flush()
        # temp=20 exactly hits the first item (factor 2.0): the (T,F,F) combo
        # early-returns 2.0, and the geometric combination lifts it to 2.0¹ = 2.0
        assert _EnvCalc(eg).env_factor(h) == pytest.approx(2.0)
    finally:
        _close(cm, ctx)


# ---------------------------------------------------------------------------
# generate_schedule — the remaining _gen_valve branches
# ---------------------------------------------------------------------------


def test_gen_already_scheduled_sets_priority(engine):
    """A valve with future scheduled time keeps it and adjusts priority only."""
    sess, cm, ctx, objs = _seed(engine, valve_level=8.0)
    try:
        mgr = Mgr(sess)
        v1 = objs["v1"]
        sess.add(r.Schedule(valve=v1, start=datetime(2025, 1, 1, 7, 0, tzinfo=UTC), duration=100))
        sess.flush()
        res = generate_schedule(
            mgr, site="home", start=T0, delay=timedelta(0), horizon=timedelta(days=1), log=_swallow
        )
        # has=100s already queued; want=25s → priority = 25 > 120? No → False
        assert res == {"valves": 1, "schedules": 0, "forced": 0}
        assert len(list(mgr.scalars(select(r.Schedule)))) == 1  # only the pre-seeded one
        assert v1.priority is False
    finally:
        _close(cm, ctx)


def test_gen_too_little_to_schedule(engine):
    """A deficit under 10 s is too small to bother scheduling."""
    sess, cm, ctx, _ = _seed(engine, valve_level=4.0, start_level=4.0, stop_level=3.0)
    try:
        mgr = Mgr(sess)
        res = generate_schedule(
            mgr, site="home", start=T0, delay=timedelta(0), horizon=timedelta(days=1), log=_swallow
        )
        # want = (4 - 3) * 10 / 2 = 5 s < 10 s → too little
        assert res == {"valves": 1, "schedules": 0, "forced": 0}
        assert list(mgr.scalars(select(r.Schedule))) == []
    finally:
        _close(cm, ctx)


def test_gen_partial_clip_with_max_run(engine):
    """A slot longer than ``max_run`` is clipped, yielding a partial run."""
    sess, cm, ctx, objs = _seed(
        engine, valve_level=23.0, start_level=23.0, stop_level=3.0, max_level=30.0, max_run=30
    )
    try:
        mgr = Mgr(sess)
        res = generate_schedule(
            mgr, site="home", start=T0, delay=timedelta(0), horizon=timedelta(days=1), log=_swallow
        )
        # want = (23 - 3) * 10 / 2 = 100 s; max_run=30 → clip to 30 s < want → partial
        assert res == {"valves": 1, "schedules": 1, "forced": 0}
        s = mgr.scalars(select(r.Schedule)).first()
        assert s.duration == 30
        assert s.forced is False
        assert objs["v1"].priority is True
    finally:
        _close(cm, ctx)


def test_gen_slot_too_short_then_missing(engine):
    """Slots shorter than want/5 are skipped; exhausting the window logs 'missing'."""
    sess, cm, ctx, _ = _seed(
        engine, valve_level=4323.0, start_level=4323.0, stop_level=3.0, max_level=5000.0
    )
    try:
        mgr = Mgr(sess)
        res = generate_schedule(
            mgr, site="home", start=T0, delay=timedelta(0), horizon=timedelta(days=1), log=_swallow
        )
        # want = 4320 * 10 / 2 = 21600 s (6 h); each 1 h slot < 4320 s (want/5) → too short
        assert res == {"valves": 1, "schedules": 0, "forced": 0}
        assert list(mgr.scalars(select(r.Schedule))) == []
    finally:
        _close(cm, ctx)


def test_gen_save_false_inserts_nothing(engine):
    """``save=False`` runs the planner but persists no schedules."""
    sess, cm, ctx, _ = _seed(engine, valve_level=8.0)
    try:
        mgr = Mgr(sess)
        res = generate_schedule(
            mgr, site="home", start=T0, delay=timedelta(0), horizon=timedelta(days=1), save=False
        )
        assert res == {"valves": 1, "schedules": 0, "forced": 0}
        assert list(mgr.scalars(select(r.Schedule))) == []
    finally:
        _close(cm, ctx)


def test_gen_defers_slots_past_soon(engine):
    """A slot starting after ``soon`` is deferred to the next run (no schedule)."""
    sess, cm, ctx, _ = _seed(engine, valve_level=8.0)
    try:
        mgr = Mgr(sess)
        res = generate_schedule(
            mgr, site="home", start=T0, delay=timedelta(hours=2), horizon=timedelta(days=2)
        )
        # soon = 08:00; the 06:00 hour is past, next is Jan2 06:00 > soon → defer
        assert res == {"valves": 1, "schedules": 0, "forced": 0}
        assert list(mgr.scalars(select(r.Schedule))) == []
    finally:
        _close(cm, ctx)


# ---------------------------------------------------------------------------
# recalculate — clamps, age, and the unchanged path
# ---------------------------------------------------------------------------


def test_recalculate_clamps_at_max_level(engine):
    """Evaporation past ``max_level`` (with flow or rain) is clamped before delivery."""
    sess, cm, ctx, objs = _seed_recalc(engine)
    try:
        mgr = Mgr(sess)
        v = objs["v"]
        site = objs["site"]
        sess.add(
            r.Level(
                valve=v, time=datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC), level=9.9, forced=True
            )
        )
        sess.add(
            r.Level(
                valve=v,
                time=datetime(2025, 1, 1, 1, 0, 0, tzinfo=UTC),
                level=9.9,
                forced=False,
                flow=5.0,
            )
        )
        sess.add(r.History(site=site, time=datetime(2025, 1, 1, 0, 30, 0, tzinfo=UTC), rain=0.0))
        sess.flush()
        recalculate(mgr, site="home", log=_swallow)
        levels = list(mgr.scalars(select(r.Level).order_by(r.Level.time)))
        # 9.9 + evap(0.208) = 10.108 → clamp to 10; then − flow/area(0.5) = 9.5
        assert levels[1].level == pytest.approx(9.5)
    finally:
        _close(cm, ctx)


def test_recalculate_with_age_back_to_the_forced_anchor(engine):
    """A wide ``age`` reaches back past the data, landing on the forced anchor."""
    sess, cm, ctx, objs = _seed_recalc(engine)
    try:
        mgr = Mgr(sess)
        v = objs["v"]
        site = objs["site"]
        sess.add(
            r.Level(
                valve=v, time=datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC), level=5.0, forced=True
            )
        )
        sess.add(
            r.Level(
                valve=v, time=datetime(2025, 1, 1, 1, 0, 0, tzinfo=UTC), level=5.0, forced=False
            )
        )
        sess.add(r.History(site=site, time=datetime(2025, 1, 1, 0, 30, 0, tzinfo=UTC), rain=0.0))
        sess.flush()
        recalculate(mgr, site="home", age=timedelta(days=365 * 10))
        levels = list(mgr.scalars(select(r.Level).order_by(r.Level.time)))
        assert levels[1].level == pytest.approx(5.0 + 10 / 86400 * 1800)
    finally:
        _close(cm, ctx)


def test_recalculate_unchanged_level_not_rewritten(engine):
    """A level that recomputes to within 1 % of its stored value is left alone."""
    sess, cm, ctx, objs = _seed_recalc(engine)
    try:
        mgr = Mgr(sess)
        v = objs["v"]
        # no history → no evap → recomputed level equals stored → no update
        sess.add(
            r.Level(
                valve=v, time=datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC), level=5.0, forced=True
            )
        )
        sess.add(
            r.Level(
                valve=v, time=datetime(2025, 1, 1, 1, 0, 0, tzinfo=UTC), level=5.0, forced=False
            )
        )
        sess.flush()
        res = recalculate(mgr, site="home")
        assert res == {"valves": 1, "updated": 0}
        levels = list(mgr.scalars(select(r.Level).order_by(r.Level.time)))
        assert levels[1].level == 5.0
        assert v.level == 5.0
    finally:
        _close(cm, ctx)


# ---------------------------------------------------------------------------
# controller / feed / group — further heap and composition coverage
# ---------------------------------------------------------------------------


def test_controller_range_max_on_two_overlapping(engine):
    """With ``max_on=2`` and two overlapping runs, the gap before saturation is yielded."""
    sess, cm, ctx, objs = _seed(engine, max_on=2)
    try:
        ctrl = objs["ctrl"]
        feed = objs["feed"]
        eg = objs["eg"]
        v1 = objs["v1"]
        v2 = r.Valve(
            name="V2",
            controller=ctrl,
            feed=feed,
            envgroup=eg,
            location="q",
            flow=2.0,
            area=10.0,
            level=0.0,
        )
        sess.add(v2)
        sess.add(
            r.Schedule(valve=v1, start=datetime(2025, 1, 1, 6, 0, 0, tzinfo=UTC), duration=60)
        )
        sess.add(
            r.Schedule(valve=v2, start=datetime(2025, 1, 1, 6, 0, 30, tzinfo=UTC), duration=60)
        )
        sess.flush()
        spans = list(
            controller_range(
                Mgr(sess),
                ctrl,
                datetime(2025, 1, 1, 6, 0, tzinfo=UTC),
                datetime(2025, 1, 1, 6, 5, 0, tzinfo=UTC),
            )
        )
        # saturated once V2 starts at 06:00:30 → yield [06:00, 06:00:30); then free after 06:01
        assert spans[0] == (_n(2025, 1, 1, 6, 0), timedelta(seconds=30))
        assert spans[1][0] == _n(2025, 1, 1, 6, 1)
    finally:
        _close(cm, ctx)


def test_group_range_composes_overrides(engine):
    """``group_range`` widens with allowed and narrows with disallowed overrides."""
    sess, cm, ctx, objs = _seed(engine)
    try:
        g = objs["g"]
        sess.add(
            r.GroupOverride(
                group=g, allowed=True, start=datetime(2025, 1, 1, 8, 0, tzinfo=UTC), duration=3600
            )
        )
        sess.add(
            r.GroupOverride(
                group=g,
                allowed=False,
                start=datetime(2025, 1, 1, 6, 30, tzinfo=UTC),
                duration=1800,
            )
        )
        sess.flush()
        spans = list(
            group_range(
                Mgr(sess),
                g,
                datetime(2025, 1, 1, 6, 0, tzinfo=UTC),
                datetime(2025, 1, 1, 9, 0, tzinfo=UTC),
            )
        )
        # 06:00 hour minus [06:30, 07:00) → [06:00, 06:30); plus the allowed [08:00, 09:00)
        assert spans == [
            (_n(2025, 1, 1, 6, 0), timedelta(minutes=30)),
            (_n(2025, 1, 1, 8, 0), timedelta(hours=1)),
        ]
    finally:
        _close(cm, ctx)


# ---------------------------------------------------------------------------
# remaining branch coverage
# ---------------------------------------------------------------------------


def test_gen_nothing_to_do_when_below_start_level(engine):
    """A valve already below its start level (and not priority) needs nothing."""
    sess, cm, ctx, _ = _seed(engine, valve_level=2.0, start_level=8.0)
    try:
        mgr = Mgr(sess)
        res = generate_schedule(
            mgr, site="home", start=T0, delay=timedelta(0), horizon=timedelta(days=1), log=_swallow
        )
        # level=2 < start_level=8 (and priority False) → nothing to do
        assert res == {"valves": 1, "schedules": 0, "forced": 0}
        assert list(mgr.scalars(select(r.Schedule))) == []
    finally:
        _close(cm, ctx)


def test_recalculate_no_levels_does_nothing(engine):
    """A valve with no level rows is visited but nothing is updated."""
    sess, cm, ctx, objs = _seed_recalc(engine)
    try:
        mgr = Mgr(sess)
        res = recalculate(mgr, site="home")
        assert res == {"valves": 1, "updated": 0}
        assert objs["v"].level == 5.0
    finally:
        _close(cm, ctx)


def test_past_schedule_and_override_are_skipped(engine):
    """Rows ending before the window start are skipped (the ``continue`` branches)."""
    sess, cm, ctx, objs = _seed(engine)
    try:
        v1 = objs["v1"]
        g = objs["g"]
        # a schedule and an override wholly in the past (before 06:00)
        sess.add(r.Schedule(valve=v1, start=datetime(2025, 1, 1, 4, 0, tzinfo=UTC), duration=60))
        sess.add(
            r.ValveOverride(
                valve=v1, running=False, start=datetime(2025, 1, 1, 4, 0, tzinfo=UTC), duration=60
            )
        )
        sess.add(
            r.GroupOverride(
                group=g, allowed=False, start=datetime(2025, 1, 1, 4, 0, tzinfo=UTC), duration=60
            )
        )
        sess.flush()
        # the 06:00 hour is unaffected by the 04:00 rows
        spans = list(
            valve_range(
                Mgr(sess),
                v1,
                datetime(2025, 1, 1, 6, 0, tzinfo=UTC),
                datetime(2025, 1, 1, 7, 0, tzinfo=UTC),
            )
        )
        assert spans == [(_n(2025, 1, 1, 6, 0), timedelta(hours=1))]
    finally:
        _close(cm, ctx)


def test_env_factor_uses_wind_only_items(engine):
    """A wind-only data point feeds the (F,T,F) combo's inverse-distance path."""
    sess, cm, ctx = _mgr(engine)
    try:
        site = r.Site(name="home")
        eg = r.EnvGroup(name="std", site=site, factor=1.0)
        r.EnvItem(group=eg, factor=1.0, wind=0.0)
        r.EnvItem(group=eg, factor=3.0, wind=4.0)
        sess.add_all([site, eg])
        sess.flush()
        h = r.History(site=site, time=datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC), wind=2.0)
        sess.add(h)
        sess.flush()
        # equidistant in wind → (1.0 + 3.0) / 2 = 2.0
        assert _EnvCalc(eg).env_factor(h) == pytest.approx(2.0)
    finally:
        _close(cm, ctx)


def test_generate_schedule_without_site_filter_joins_nothing(engine):
    """``site=None`` skips the controller join in :func:`_select_valves`."""
    sess, cm, ctx, _ = _seed(engine, valve_level=8.0)
    try:
        mgr = Mgr(sess)
        # site=None selects across all sites (here just one); no join needed
        res = generate_schedule(
            mgr, site=None, start=T0, delay=timedelta(0), horizon=timedelta(days=1), log=_swallow
        )
        assert res == {"valves": 1, "schedules": 1, "forced": 0}
    finally:
        _close(cm, ctx)


def test_feed_range_single_valve_mode_via_over_demand(engine):
    """A valve whose flow exceeds the feed's capacity triggers single-valve mode."""
    sess, cm, ctx, objs = _seed(engine, feed_flow=2.0, flow=3.0)
    try:
        feed = objs["feed"]
        v1 = objs["v1"]
        sess.add(r.Schedule(valve=v1, start=datetime(2025, 1, 1, 6, 0, tzinfo=UTC), duration=40))
        sess.flush()
        spans = list(
            feed_range(
                Mgr(sess),
                feed,
                datetime(2025, 1, 1, 6, 0, tzinfo=UTC),
                datetime(2025, 1, 1, 6, 5, 0, tzinfo=UTC),
                3.0,
                add=timedelta(seconds=30),
            )
        )
        # feed.flow(2) - plusflow(3) < 0 → single-valve mode: free after the run + slack
        assert spans[0][0] == _n(2025, 1, 1, 6, 1, 10)
    finally:
        _close(cm, ctx)


def test_feed_range_single_valve_pops_between_runs(engine):
    """In single-valve mode, a gap between two runs is yielded (the while-loop path)."""
    sess, cm, ctx, objs = _seed(engine, feed_flow=2.0, flow=3.0)
    try:
        feed = objs["feed"]
        v1 = objs["v1"]
        sess.add(r.Schedule(valve=v1, start=datetime(2025, 1, 1, 6, 0, tzinfo=UTC), duration=40))
        sess.add(r.Schedule(valve=v1, start=datetime(2025, 1, 1, 6, 2, tzinfo=UTC), duration=40))
        sess.flush()
        spans = list(
            feed_range(
                Mgr(sess),
                feed,
                datetime(2025, 1, 1, 6, 0, tzinfo=UTC),
                datetime(2025, 1, 1, 6, 5, 0, tzinfo=UTC),
                3.0,
                add=timedelta(seconds=30),
            )
        )
        # over-demand → single-valve mode; gap [06:01:10, 06:02:00) freed between the runs
        assert spans[0] == (_n(2025, 1, 1, 6, 1, 10), timedelta(seconds=50))
    finally:
        _close(cm, ctx)


def test_env_factor_uses_sun_only_items(engine):
    """Sun-only data points feed the (F,F,T) combo's inverse-distance path."""
    sess, cm, ctx = _mgr(engine)
    try:
        site = r.Site(name="home")
        eg = r.EnvGroup(name="std", site=site, factor=1.0)
        r.EnvItem(group=eg, factor=1.0, sun=0.0)
        r.EnvItem(group=eg, factor=3.0, sun=0.5)
        sess.add_all([site, eg])
        sess.flush()
        h = r.History(site=site, time=datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC), sun=0.25)
        sess.add(h)
        sess.flush()
        assert _EnvCalc(eg).env_factor(h) == pytest.approx(2.0)
    finally:
        _close(cm, ctx)


def test_past_rows_skipped_per_function(engine):
    """A past row hits the ``continue`` skip in each override/schedule query function."""
    sess, cm, ctx, objs = _seed(engine)
    try:
        v1 = objs["v1"]
        g = objs["g"]
        ctrl = objs["ctrl"]
        feed = objs["feed"]
        sess.add(r.Schedule(valve=v1, start=datetime(2025, 1, 1, 4, 0, tzinfo=UTC), duration=60))
        sess.add(
            r.ValveOverride(
                valve=v1, running=False, start=datetime(2025, 1, 1, 4, 0, tzinfo=UTC), duration=60
            )
        )
        sess.add(
            r.GroupOverride(
                group=g, allowed=False, start=datetime(2025, 1, 1, 4, 0, tzinfo=UTC), duration=60
            )
        )
        sess.flush()
        mgr = Mgr(sess)
        win = (_n(2025, 1, 1, 6, 0), timedelta(hours=1))
        s, e = datetime(2025, 1, 1, 6, 0, tzinfo=UTC), datetime(2025, 1, 1, 7, 0, tzinfo=UTC)
        assert list(group_not_blocked_range(mgr, g, s, e)) == [win]
        assert list(valve_not_blocked_range(mgr, v1, s, e)) == [win]
        assert list(valve_not_scheduled(mgr, v1, s, e)) == [win]
        assert list(controller_range(mgr, ctrl, s, e)) == [win]
        assert list(feed_range(mgr, feed, s, e, 2.0)) == [win]
    finally:
        _close(cm, ctx)


def test_generate_schedule_filters_by_controller(engine):
    """The ``controller=`` name filter narrows the valve selection."""
    sess, cm, ctx, _ = _seed(engine, valve_level=8.0)
    try:
        mgr = Mgr(sess)
        res = generate_schedule(
            mgr,
            site="home",
            controller="C1",
            start=T0,
            delay=timedelta(0),
            horizon=timedelta(days=1),
            log=_swallow,
        )
        assert res == {"valves": 1, "schedules": 1, "forced": 0}
    finally:
        _close(cm, ctx)


def test_recalculate_promotes_earliest_with_age(engine):
    """With ``age`` set and no forced level, the earliest level is promoted via the age filter."""
    sess, cm, ctx, objs = _seed_recalc(engine)
    try:
        mgr = Mgr(sess)
        v = objs["v"]
        site = objs["site"]
        sess.add(
            r.Level(
                valve=v, time=datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC), level=5.0, forced=False
            )
        )
        sess.add(
            r.Level(
                valve=v, time=datetime(2025, 1, 1, 1, 0, 0, tzinfo=UTC), level=5.0, forced=False
            )
        )
        sess.add(r.History(site=site, time=datetime(2025, 1, 1, 0, 30, 0, tzinfo=UTC), rain=0.0))
        sess.flush()
        recalculate(mgr, site="home", age=timedelta(days=365 * 10), log=_swallow)
        levels = list(mgr.scalars(select(r.Level).order_by(r.Level.time)))
        assert levels[0].forced is True
        assert levels[1].level == pytest.approx(5.0 + 10 / 86400 * 1800)
    finally:
        _close(cm, ctx)


def test_controller_range_drains_between_sequential_runs(engine):
    """``max_on=1`` with two non-overlapping runs pops the heap between them."""
    sess, cm, ctx, objs = _seed(engine, max_on=1)
    try:
        ctrl = objs["ctrl"]
        feed = objs["feed"]
        eg = objs["eg"]
        v1 = objs["v1"]
        v2 = r.Valve(
            name="V2",
            controller=ctrl,
            feed=feed,
            envgroup=eg,
            location="q",
            flow=2.0,
            area=10.0,
            level=0.0,
        )
        sess.add(v2)
        # first run ends at 06:00:40; second starts at 06:01 (after the stop)
        sess.add(r.Schedule(valve=v1, start=datetime(2025, 1, 1, 6, 0, tzinfo=UTC), duration=40))
        sess.add(r.Schedule(valve=v2, start=datetime(2025, 1, 1, 6, 1, tzinfo=UTC), duration=40))
        sess.flush()
        spans = list(
            controller_range(
                Mgr(sess),
                ctrl,
                datetime(2025, 1, 1, 6, 0, tzinfo=UTC),
                datetime(2025, 1, 1, 6, 5, tzinfo=UTC),
            )
        )
        # gap [06:00:40, 06:01:00) freed when the heap pops before V2 starts
        assert spans[0] == (_n(2025, 1, 1, 6, 0, 40), timedelta(seconds=20))
    finally:
        _close(cm, ctx)


def test_feed_range_normal_mode_pops_between_runs(engine):
    """In normal capacity mode, the heap pops between two runs (the ``else`` branch)."""
    sess, cm, ctx, objs = _seed(engine, feed_flow=10.0, flow=2.0)
    try:
        feed = objs["feed"]
        v1 = objs["v1"]
        sess.add(r.Schedule(valve=v1, start=datetime(2025, 1, 1, 6, 0, tzinfo=UTC), duration=40))
        sess.add(r.Schedule(valve=v1, start=datetime(2025, 1, 1, 6, 2, tzinfo=UTC), duration=40))
        sess.flush()
        spans = list(
            feed_range(
                Mgr(sess),
                feed,
                datetime(2025, 1, 1, 6, 0, tzinfo=UTC),
                datetime(2025, 1, 1, 6, 5, tzinfo=UTC),
                2.0,
                add=timedelta(seconds=30),
            )
        )
        # capacity 10 - 2 = 8; one run draws 2 → 6 left; gap freed before the second run
        assert spans[0][0] == _n(2025, 1, 1, 6, 0)
    finally:
        _close(cm, ctx)


def test_valve_not_blocked_skips_past_override(engine):
    """A past off override is skipped (the ``continue`` branch) by ``valve_not_blocked_range``."""
    sess, cm, ctx, objs = _seed(engine)
    try:
        v1 = objs["v1"]
        sess.add(
            r.ValveOverride(
                valve=v1, running=False, start=datetime(2025, 1, 1, 4, 0, tzinfo=UTC), duration=60
            )
        )
        sess.flush()
        spans = list(
            valve_not_blocked_range(
                Mgr(sess),
                v1,
                datetime(2025, 1, 1, 6, 0, tzinfo=UTC),
                datetime(2025, 1, 1, 7, 0, tzinfo=UTC),
            )
        )
        assert spans == [(_n(2025, 1, 1, 6, 0), timedelta(hours=1))]
    finally:
        _close(cm, ctx)


def test_recalculate_zero_clamps_negative_dryness(engine):
    """A level driven negative by prior rain, with no later rain/flow, clamps to zero."""
    sess, cm, ctx, objs = _seed_recalc(engine)
    try:
        mgr = Mgr(sess)
        v = objs["v"]
        site = objs["site"]
        sess.add(
            r.Level(valve=v, time=datetime(2025, 1, 1, 0, 0, tzinfo=UTC), level=5.0, forced=True)
        )
        sess.add(
            r.Level(valve=v, time=datetime(2025, 1, 1, 1, 0, tzinfo=UTC), level=5.0, forced=False)
        )
        sess.add(
            r.Level(valve=v, time=datetime(2025, 1, 1, 2, 0, tzinfo=UTC), level=5.0, forced=False)
        )
        sess.add(r.History(site=site, time=datetime(2025, 1, 1, 0, 30, tzinfo=UTC), rain=10.0))
        sess.add(r.History(site=site, time=datetime(2025, 1, 1, 1, 30, tzinfo=UTC), rain=0.0))
        sess.flush()
        recalculate(mgr, site="home", log=_swallow)
        levels = list(mgr.scalars(select(r.Level).order_by(r.Level.time)))
        # T1: 5 + evap - rain(10) → negative (no zero-clamp, rain>0); T2: carried negative + evap, no rain → clamp to 0
        assert levels[1].level < 0
        assert levels[2].level == 0
    finally:
        _close(cm, ctx)


def test_watering_time_defaults_to_start_level():
    """``_watering_time`` with no level uses the valve's ``start_level``."""
    v = r.Valve(start_level=8.0, stop_level=3.0, area=10.0, flow=2.0)
    # (8 - 3) * 10 / 2 = 25 s
    assert _watering_time(v) == timedelta(seconds=25)
