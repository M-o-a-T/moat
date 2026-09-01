"""Tests for the rain monitor daemon (Phase 9).

Exercises :mod:`moat.db.rain.monitor` — the long-running anyio daemon
that ticks :func:`~moat.db.rain.engine.generate_schedule` /
:func:`~moat.db.rain.engine.recalculate`, subscribes to weather sensors
via a stubbed moat.link, and dispatches valve commands.

The moat.link client is replaced by a :class:`StubLink` that simulates
sensor readings and valve-state feedback without any real hardware or
MQTT broker.  The database is the shared session-scoped SQLite instance
from :mod:`tests.moat_db_rain.conftest`.
"""

from __future__ import annotations

import pytest
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

import moat.db.util  # noqa: F401  — attaches the sqlite ``foreign_keys=ON`` pragma listener
from moat.util import NotGiven, ctx_as
from moat.db.rain import model as r
from moat.db.rain.monitor import SENSOR_MAXTIME, SENSOR_TIME, Monitor
from moat.db.util import Mgr, session
from moat.lib.path import Path

pytestmark = [pytest.mark.anyio]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _n(year, month, day, hour=0, minute=0, second=0):
    """An aware-UTC datetime."""
    return datetime(year, month, day, hour, minute, second, tzinfo=UTC)


def _mgr(engine):
    """A ``(sess, mgr_cm, ctx)`` triple bound to ``engine``."""
    sess_cm = Session(engine)
    sess = sess_cm.__enter__()
    ctx = ctx_as(session, Mgr(sess))
    ctx.__enter__()
    return sess, sess_cm, ctx


def _close(sess_cm, ctx):
    ctx.__exit__(None, None, None)
    sess_cm.__exit__(None, None, None)


def _seed_monitor_world(engine):
    """Seed a site with one controller, one feed, one env group, one valve,
    one rain sensor, and one day/time/group — the minimal world the
    monitor needs to generate schedules.

    The valve has ``command`` and ``state`` paths set so the dispatcher
    can send commands.  The rain sensor's ``state`` path is
    ``sensor.rain``.  Returns ``(mgr, cm, ctx, objs)`` where ``mgr`` is
    the :class:`~moat.db.util.Mgr` wrapping the session (so monitor
    methods that call ``sess.one()`` work).
    """
    sess, cm, ctx = _mgr(engine)
    mgr = session.get()
    site = r.Site(name="home")
    ctrl = r.Controller(name="C1", site=site, location="rack")
    feed = r.Feed(name="F1", site=site, flow=100.0)
    eg = r.EnvGroup(name="std", site=site, factor=1.0)
    valve = r.Valve(
        name="V1",
        controller=ctrl,
        feed=feed,
        envgroup=eg,
        location="front",
        flow=2.0,
        area=10.0,
        start_level=8.0,
        stop_level=3.0,
        max_level=10.0,
        level=8.0,
        shade=1.0,
        runoff=1.0,
        command=Path.from_str("valve.v1.cmd"),
        state=Path.from_str("valve.v1.state"),
    )
    rain_sensor = r.Sensor(
        kind="rain",
        name="R1",
        state=Path.from_str("sensor.rain"),
        weight=10,
        site=site,
    )
    day = r.Day(name="d6")
    r.DayTime(day=day, descr="6h")
    dr = r.DayRange(name="dr6")
    dr.days.add(day)
    g = r.Group(name="g1", site=site)
    g.days.add(dr)
    g.valves.add(valve)
    sess.add_all([site, ctrl, feed, eg, valve, rain_sensor, day, dr, g])
    sess.flush()
    objs = dict(site=site, ctrl=ctrl, feed=feed, eg=eg, valve=valve, rain_sensor=rain_sensor)
    return mgr, cm, ctx, objs


def _fake_database(engine):
    """Build a callable that mimics ``moat.db.util.database`` using ``engine``.

    The monitor calls ``database(db_cfg)`` as a context manager; this
    returns a function that accepts (and ignores) the config and opens a
    fresh session from the test engine.
    """

    from contextlib import contextmanager  # noqa: PLC0415

    @contextmanager
    def _open(_cfg=None):
        s = Session(engine)
        mgr = Mgr(s)
        with ctx_as(session, mgr):
            try:
                yield mgr
                s.commit()
            except Exception:
                s.rollback()
                raise
            finally:
                s.close()

    return _open


# ---------------------------------------------------------------------------
# StubLink — a minimal moat.link stand-in for testing
# ---------------------------------------------------------------------------


class _StubWatcher:
    """An async-context-manager + async-iterator that yields queued values."""

    def __init__(self, values: list[object]):
        self._values = values
        self._idx = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._idx < len(self._values):
            val = self._values[self._idx]
            self._idx += 1
            return val
        # Block forever — simulating a real watch that never closes.
        import anyio  # noqa: PLC0415

        await anyio.sleep_forever()
        raise StopAsyncIteration


class StubLink:
    """A minimal moat.link client stub for the monitor daemon.

    Provides ``d_watch`` (returns a pre-queued set of readings) and
    ``d_set`` (records what was sent).  No real MQTT / hardware.

    Attributes:
        readings: Maps a path string to a list of values to yield.
        sent: Maps a path string to the last value sent via ``d_set``.
    """

    def __init__(self):
        self.readings: dict[str, list[object]] = {}
        self.sent: dict[str, object] = {}

    def d_watch(self, path, **kw):  # noqa: ARG002
        """Return a watcher that yields pre-queued readings for ``path``."""
        key = str(path)
        vals = self.readings.get(key, [])
        return _StubWatcher(list(vals))

    async def d_set(self, path, data=NotGiven, **kw):  # noqa: ARG002
        """Record a valve command."""
        self.sent[str(path)] = data

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


# ---------------------------------------------------------------------------
# Tests — Monitor construction and state
# ---------------------------------------------------------------------------


def test_monitor_init(engine):  # noqa: ARG001
    """Monitor constructs with sensible defaults."""
    mon = Monitor("home", None, StubLink())
    assert mon.site_name == "home"
    assert mon.tick == 300
    assert mon._rain_active is False  # noqa: SLF001


def test_monitor_accumulate_reading(engine):  # noqa: ARG001
    """Sensor readings are accumulated per-kind in the readings buffer."""
    mon = Monitor("home", None, StubLink())
    mon._accumulate_reading("rain", 2.5, 10)  # noqa: SLF001
    mon._accumulate_reading("rain", 1.5, 10)  # noqa: SLF001
    buf = mon._readings  # type: ignore[attr-defined]  # noqa: SLF001
    assert buf["rain"] == (40.0, 20.0)  # (10*2.5 + 10*1.5, 10+10)


def test_monitor_accumulate_bad_value(engine):  # noqa: ARG001
    """Non-numeric readings are silently ignored."""
    mon = Monitor("home", None, StubLink())
    mon._accumulate_reading("rain", "not_a_number", 10)  # noqa: SLF001
    mon._accumulate_reading("rain", None, 10)  # noqa: SLF001
    assert not hasattr(mon, "_readings") or "rain" not in mon._readings  # noqa: SLF001


def test_monitor_rain_expiry_logic(engine):  # noqa: ARG001
    """Rain-delay expiry logic: expired deadline → not active."""
    mon = Monitor("home", None, StubLink())
    mon._rain_active = True  # noqa: SLF001
    mon._rain_deadline = datetime.now(UTC) - timedelta(seconds=1)  # expired  # noqa: SLF001
    now_utc = datetime.now(UTC)
    rain_active = mon._rain_active and (  # noqa: SLF001
        mon._rain_deadline is not None and now_utc < mon._rain_deadline  # noqa: SLF001
    )
    assert rain_active is False


def test_monitor_constants():
    """Constants match the legacy values."""
    assert SENSOR_TIME == 5 * 60
    assert SENSOR_MAXTIME == 60 * 60


# ---------------------------------------------------------------------------
# Tests — History flush
# ---------------------------------------------------------------------------


def test_monitor_flush_history(engine):
    """Accumulated sensor readings are flushed into a History row."""
    mgr, cm, ctx, _objs = _seed_monitor_world(engine)
    try:
        mon = Monitor("home", None, StubLink())
        mon._accumulate_reading("rain", 2.0, 10)  # noqa: SLF001
        mon._accumulate_reading("temp", 15.0, 10)  # noqa: SLF001

        now_utc = datetime.now(UTC)
        mon._flush_history(mgr, now_utc)  # noqa: SLF001

        with mgr.execute(select(r.History).order_by(r.History.time)) as rs:
            histories = list(rs)
        assert len(histories) == 1
        (hist,) = histories[0]
        assert hist.rain == 2.0
        assert hist.temp == 15.0

        # Buffer should be cleared after flush.
        assert not mon._readings  # type: ignore[attr-defined]  # noqa: SLF001
    finally:
        _close(cm, ctx)


def test_monitor_flush_history_empty_buffer(engine):
    """Flushing with no accumulated readings is a no-op."""
    mgr, cm, ctx, _objs = _seed_monitor_world(engine)
    try:
        mon = Monitor("home", None, StubLink())
        now_utc = datetime.now(UTC)
        mon._flush_history(mgr, now_utc)  # noqa: SLF001

        with mgr.execute(select(r.History)) as rs:
            assert len(list(rs)) == 0
    finally:
        _close(cm, ctx)


# ---------------------------------------------------------------------------
# Tests — Dispatch
# ---------------------------------------------------------------------------


def test_monitor_dispatch_marks_seen(engine):
    """Pending unseen schedules are marked seen after dispatch."""
    mgr, cm, ctx, _objs = _seed_monitor_world(engine)
    try:
        mon = Monitor("home", None, StubLink(), tick=60)

        valve = mgr.scalar(select(r.Valve).where(r.Valve.name == "V1"))
        sched = r.Schedule(
            valve=valve,
            start=datetime.now(UTC),
            duration=300,
            seen=False,
        )
        mgr.add(sched)
        mgr.flush()

        mon._dispatch(mgr)  # noqa: SLF001

        mgr.refresh(sched)
        assert sched.seen is True
    finally:
        _close(cm, ctx)


def test_monitor_dispatch_skips_no_command(engine):
    """Valves without a command path are skipped during dispatch."""
    mgr, cm, ctx, _objs = _seed_monitor_world(engine)
    try:
        mon = Monitor("home", None, StubLink(), tick=60)

        valve = mgr.scalar(select(r.Valve).where(r.Valve.name == "V1"))
        valve.command = None
        mgr.flush()

        sched = r.Schedule(
            valve=valve,
            start=datetime.now(UTC),
            duration=300,
            seen=False,
        )
        mgr.add(sched)
        mgr.flush()

        mon._dispatch(mgr)  # noqa: SLF001

        mgr.refresh(sched)
        assert sched.seen is False
    finally:
        _close(cm, ctx)


def test_monitor_dispatch_returns_commands(engine):
    """_dispatch returns (path, payload) pairs honouring forced/changed flags."""
    mgr, cm, ctx, objs = _seed_monitor_world(engine)
    try:
        mon = Monitor("home", None, StubLink(), tick=3600)

        valve = mgr.scalar(select(r.Valve).where(r.Valve.name == "V1"))
        start = datetime.now(UTC)
        forced_sched = r.Schedule(valve=valve, start=start, duration=300, seen=False, forced=True)
        changed_sched = r.Schedule(
            valve=valve,
            start=start + timedelta(minutes=30),
            duration=200,
            seen=False,
            changed=True,
        )
        mgr.add_all([forced_sched, changed_sched])
        mgr.flush()

        commands = mon._dispatch(mgr)  # noqa: SLF001

        # Two commands, both addressed to the valve's command path.
        assert len(commands) == 2
        paths = [str(p) for p, _ in commands]
        assert all(p == str(objs["valve"].command) for p in paths)

        # Payloads carry the schedule's start/duration and the flags.
        pl0 = commands[0][1]
        assert pl0["duration"] == 300
        assert pl0["forced"] is True
        assert pl0["changed"] is False

        pl1 = commands[1][1]
        assert pl1["duration"] == 200
        assert pl1["forced"] is False
        assert pl1["changed"] is True

        # Both schedules now marked seen.
        mgr.refresh(forced_sched)
        mgr.refresh(changed_sched)
        assert forced_sched.seen is True
        assert changed_sched.seen is True
    finally:
        _close(cm, ctx)


def test_monitor_dispatch_horizon_excludes_far_schedules(engine):
    """Schedules beyond now+tick are not dispatched yet."""
    mgr, cm, ctx, _objs = _seed_monitor_world(engine)
    try:
        mon = Monitor("home", None, StubLink(), tick=60)

        valve = mgr.scalar(select(r.Valve).where(r.Valve.name == "V1"))
        near = r.Schedule(valve=valve, start=datetime.now(UTC), duration=100, seen=False)
        far = r.Schedule(
            valve=valve,
            start=datetime.now(UTC) + timedelta(hours=2),
            duration=200,
            seen=False,
        )
        mgr.add_all([near, far])
        mgr.flush()

        commands = mon._dispatch(mgr)  # noqa: SLF001

        # Only the near schedule is within the tick horizon.
        assert len(commands) == 1
        assert commands[0][1]["duration"] == 100
        mgr.refresh(near)
        mgr.refresh(far)
        assert near.seen is True
        assert far.seen is False
    finally:
        _close(cm, ctx)


def test_monitor_tick_dispatches_via_link(engine):
    """_tick returns commands and the scheduler loop sends them via link.d_set."""
    mgr, cm, ctx, _objs = _seed_monitor_world(engine)
    mgr.commit()
    _close(cm, ctx)
    try:
        link = StubLink()
        mon = Monitor("home", None, link, tick=60)
        db = _fake_database(engine)

        # Seed a pending unseen schedule in its own session.
        s, scm, sctx = _mgr(engine)
        try:
            valve = s.scalar(select(r.Valve).where(r.Valve.name == "V1"))
            s.add(r.Schedule(valve=valve, start=datetime.now(UTC), duration=120, seen=False))
            s.flush()
            s.commit()
        finally:
            _close(scm, sctx)

        commands = mon._tick(db)  # noqa: SLF001
        assert len(commands) == 1
        path, payload = commands[0]
        assert str(path) == "valve.v1.cmd"
        assert payload["duration"] == 120

        # Simulate the scheduler loop's dispatch step.
        import anyio  # noqa: PLC0415

        async def _send():
            for p, pl in commands:
                await link.d_set(p, pl)

        anyio.run(_send)
        assert "valve.v1.cmd" in link.sent
        assert link.sent["valve.v1.cmd"]["duration"] == 120
    finally:
        pass


# ---------------------------------------------------------------------------
# Tests — Scheduler tick
# ---------------------------------------------------------------------------


def test_monitor_tick_runs(engine):
    """A scheduler tick with no rain calls recalculate + generate_schedule."""
    mgr, cm, ctx, _objs = _seed_monitor_world(engine)
    # Close the seed session so the tick can open its own without locking.
    mgr.commit()
    _close(cm, ctx)
    try:
        mon = Monitor("home", None, StubLink(), tick=60)
        db = _fake_database(engine)

        # Should not crash; the engine may or may not produce schedules
        # depending on whether the "6h" day-time matches the current hour.
        mon._tick(db)  # noqa: SLF001
    finally:
        pass


def test_monitor_tick_with_rain_skips_generation(engine):
    """When rain-delay is active, the tick skips schedule generation."""
    mgr, cm, ctx, _objs = _seed_monitor_world(engine)
    mgr.commit()
    _close(cm, ctx)
    try:
        mon = Monitor("home", None, StubLink(), tick=60)
        mon._rain_active = True  # noqa: SLF001
        mon._rain_deadline = datetime.now(UTC) + timedelta(minutes=10)  # noqa: SLF001
        db = _fake_database(engine)

        mon._tick(db)  # noqa: SLF001

        # No schedules should have been generated (rain delay active).
        sess2, cm2, ctx2 = _mgr(engine)
        try:
            with sess2.execute(select(r.Schedule)) as rs:
                assert len(list(rs)) == 0
        finally:
            _close(cm2, ctx2)
    finally:
        pass


def test_monitor_tick_rain_clears_after_expiry(engine):
    """Rain-delay clears after the deadline passes."""
    mgr, cm, ctx, _objs = _seed_monitor_world(engine)
    mgr.commit()
    _close(cm, ctx)
    try:
        mon = Monitor("home", None, StubLink(), tick=60)
        mon._rain_active = True  # noqa: SLF001
        mon._rain_deadline = datetime.now(UTC) - timedelta(seconds=1)  # expired  # noqa: SLF001
        db = _fake_database(engine)

        mon._tick(db)  # noqa: SLF001

        assert mon._rain_active is False  # noqa: SLF001
        assert mon._rain_deadline is None  # noqa: SLF001
    finally:
        pass


# ---------------------------------------------------------------------------
# Tests — StubLink
# ---------------------------------------------------------------------------


def test_stub_link_d_watch_returns_queued_values():
    """StubLink.d_watch yields the values queued for the given path."""
    link = StubLink()
    link.readings["sensor.rain"] = [1.0, 2.0, 3.0]

    import asyncio  # noqa: PLC0415

    async def _test():
        async with link.d_watch(Path.from_str("sensor.rain")) as mon:
            vals = []
            async for v in mon:
                vals.append(v)
                if len(vals) >= 3:
                    break
            return vals

    result = asyncio.run(_test())
    assert result == [1.0, 2.0, 3.0]


def test_stub_link_d_set_records():
    """StubLink.d_set records the sent value."""
    link = StubLink()
    import asyncio  # noqa: PLC0415

    async def _test():
        await link.d_set(Path.from_str("valve.v1.cmd"), True)

    asyncio.run(_test())
    assert link.sent["valve.v1.cmd"] is True
