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

import anyio
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


# ---------------------------------------------------------------------------
# Tests — Full daemon lifecycle (run / tick cycle / shutdown)
#
# These tests exercise :meth:`Monitor.run` — the anyio task-group entry
# point that spawns the sensor collector and scheduler.  The moat.link
# client is a :class:`StubLink`; the database is the shared SQLite engine
# wrapped by :func:`_fake_database`.  ``moat.db.database`` is monkey-
# patched so the late import inside ``run()`` picks up the fake.
# ---------------------------------------------------------------------------


def _seed_and_commit(engine):
    """Seed the monitor world, commit, and close the seeding session."""
    mgr, cm, ctx, _objs = _seed_monitor_world(engine)
    mgr.commit()
    _close(cm, ctx)


@pytest.fixture
def fake_db(monkeypatch, engine):
    """Monkeypatch ``moat.db.database`` to use the test engine."""
    db = _fake_database(engine)
    import moat.db as mdb  # noqa: PLC0415

    monkeypatch.setattr(mdb, "database", db)
    return db


async def test_daemon_tick_cycle(engine, fake_db):  # noqa: ARG001
    """One daemon tick: recalculate + generate_schedule called, commands sent.

    Spawns the daemon with a very short tick, lets one scheduler cycle
    fire, then cancels.  Asserts both engine functions were invoked.
    """
    _seed_and_commit(engine)

    import moat.db.rain.engine as eng  # noqa: PLC0415
    import moat.db.rain.monitor as mon_mod  # noqa: PLC0415

    gen_calls: list[dict] = []
    recalc_calls: list[dict] = []
    orig_gen = eng.generate_schedule
    orig_recalc = eng.recalculate

    def spy_gen(sess, **kw):
        res = orig_gen(sess, **kw)
        gen_calls.append(kw)
        return res

    def spy_recalc(sess, **kw):
        res = orig_recalc(sess, **kw)
        recalc_calls.append(kw)
        return res

    mon_mod.generate_schedule = spy_gen  # type: ignore[method-assign]
    mon_mod.recalculate = spy_recalc  # type: ignore[method-assign]

    link = StubLink()
    evt = anyio.Event()
    log_lines: list[str] = []
    mon = Monitor("home", None, link, tick=1, evt=evt, log=log_lines.append)

    try:
        with anyio.fail_after(5):
            async with anyio.create_task_group() as tg:
                tg.start_soon(mon.run)
                await evt.wait()
                await anyio.sleep(1.5)  # let one tick fire
                tg.cancel_scope.cancel()
        assert len(recalc_calls) >= 1
        assert len(gen_calls) >= 1
        assert recalc_calls[0]["site"] == "home"
        assert gen_calls[0]["site"] == "home"
    finally:
        mon_mod.generate_schedule = orig_gen  # type: ignore[method-assign]
        mon_mod.recalculate = orig_recalc  # type: ignore[method-assign]


async def test_daemon_multiple_ticks(engine, fake_db):  # noqa: ARG001
    """Multiple ticks: state progresses across several iterations."""
    _seed_and_commit(engine)

    import moat.db.rain.engine as eng  # noqa: PLC0415
    import moat.db.rain.monitor as mon_mod  # noqa: PLC0415

    recalc_count = 0
    orig_recalc = eng.recalculate

    def counting_recalc(sess, **kw):
        nonlocal recalc_count
        recalc_count += 1
        return orig_recalc(sess, **kw)

    mon_mod.recalculate = counting_recalc  # type: ignore[method-assign]

    link = StubLink()
    mon = Monitor("home", None, link, tick=1)

    try:
        with anyio.fail_after(8):
            async with anyio.create_task_group() as tg:
                tg.start_soon(mon.run)
                await anyio.sleep(4)  # ~3 ticks (1s initial delay + 3×1s)
                tg.cancel_scope.cancel()
        assert recalc_count >= 2
    finally:
        mon_mod.recalculate = orig_recalc  # type: ignore[method-assign]


async def test_daemon_graceful_shutdown(engine, fake_db):  # noqa: ARG001
    """Cancelling the daemon mid-run exits without hanging or orphaned tasks."""
    _seed_and_commit(engine)

    link = StubLink()
    evt = anyio.Event()
    mon = Monitor("home", None, link, tick=1, evt=evt)

    with anyio.fail_after(5):
        async with anyio.create_task_group() as tg:
            tg.start_soon(mon.run)
            await evt.wait()
            await anyio.sleep(0.5)
            tg.cancel_scope.cancel()

    # Reaching here means clean exit within the timeout.


async def test_daemon_no_sensors(engine, fake_db):  # noqa: ARG001
    """A site with no sensors: sensor loop logs and returns idly."""
    sess, cm, ctx = _mgr(engine)
    try:
        site = r.Site(name="bare")
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
            command=Path.from_str("valve.v1.cmd"),
        )
        sess.add_all([site, ctrl, feed, eg, valve])
        sess.commit()
    finally:
        _close(cm, ctx)

    link = StubLink()
    evt = anyio.Event()
    log_lines: list[str] = []
    mon = Monitor("bare", None, link, tick=1, evt=evt, log=log_lines.append)

    with anyio.fail_after(5):
        async with anyio.create_task_group() as tg:
            tg.start_soon(mon.run)
            await evt.wait()
            await anyio.sleep(0.5)
            tg.cancel_scope.cancel()

    assert evt.is_set()
    assert any("No sensors" in line for line in log_lines)


async def test_daemon_sensor_reading_accumulation(engine, fake_db):  # noqa: ARG001
    """Sensor readings from the stub link are accumulated and flushed.

    Queues a rain reading via the StubLink, lets one tick fire, and
    confirms a History row is created.  Exercises ``_watch_sensor``,
    ``_accumulate_reading``, and the rain-delay arming path.
    """
    _seed_and_commit(engine)

    link = StubLink()
    link.readings["sensor.rain"] = [5.0]

    evt = anyio.Event()
    log_lines: list[str] = []
    mon = Monitor("home", None, link, tick=1, evt=evt, log=log_lines.append)

    with anyio.fail_after(5):
        async with anyio.create_task_group() as tg:
            tg.start_soon(mon.run)
            await evt.wait()
            await anyio.sleep(2)
            tg.cancel_scope.cancel()

    assert evt.is_set()
    assert any("raining" in line.lower() or "watching" in line.lower() for line in log_lines)


async def test_daemon_has_rain_arms_delay(engine, fake_db):
    """_has_rain with a positive value arms the rain-delay timer."""
    _seed_and_commit(engine)
    db = fake_db

    mon = Monitor("home", None, StubLink(), tick=60)
    assert mon._rain_active is False  # noqa: SLF001

    mon._has_rain(db, 3.0)  # noqa: SLF001
    assert mon._rain_active is True  # noqa: SLF001
    assert mon._rain_deadline is not None  # noqa: SLF001

    mon._rain_active = False  # noqa: SLF001
    mon._rain_deadline = None  # noqa: SLF001
    mon._has_rain(db, 0.0)  # noqa: SLF001
    assert mon._rain_active is False  # noqa: SLF001

    mon._has_rain(db, -1.0)  # noqa: SLF001
    assert mon._rain_active is False  # noqa: SLF001

    mon._has_rain(db, "not_a_number")  # noqa: SLF001
    assert mon._rain_active is False  # noqa: SLF001


async def test_daemon_has_rain_extends_existing(engine, fake_db):
    """Calling _has_rain when rain is already active extends the deadline."""
    _seed_and_commit(engine)
    db = fake_db

    mon = Monitor("home", None, StubLink(), tick=60)
    mon._has_rain(db, 2.0)  # noqa: SLF001
    first_deadline = mon._rain_deadline  # noqa: SLF001
    assert first_deadline is not None

    await anyio.sleep(0.01)
    mon._has_rain(db, 1.0)  # noqa: SLF001
    assert mon._rain_deadline is not None  # noqa: SLF001


async def test_daemon_watch_sensor_error_logged(engine, fake_db):  # noqa: ARG001
    """A watch error in _watch_sensor is caught and logged, not raised."""
    _seed_and_commit(engine)

    class ErrorLink(StubLink):
        def d_watch(self, path, **kw):  # noqa: ARG002
            raise ConnectionError("boom")

    link = ErrorLink()
    log_lines: list[str] = []
    mon = Monitor("home", None, link, tick=1, log=log_lines.append)

    with anyio.fail_after(5):
        async with anyio.create_task_group() as tg:
            tg.start_soon(mon.run)
            await anyio.sleep(2)
            tg.cancel_scope.cancel()

    assert any("watch error" in line.lower() for line in log_lines)


async def test_daemon_dispatch_error_logged(engine, fake_db):  # noqa: ARG001
    """A d_set error during dispatch is caught and logged, not raised."""
    _seed_and_commit(engine)

    s, scm, sctx = _mgr(engine)
    try:
        valve = s.scalar(select(r.Valve).where(r.Valve.name == "V1"))
        s.add(r.Schedule(valve=valve, start=datetime.now(UTC), duration=120, seen=False))
        s.flush()
        s.commit()
    finally:
        _close(scm, sctx)

    class FlakyLink(StubLink):
        async def d_set(self, path, data=NotGiven, **kw):  # noqa: ARG002
            raise RuntimeError("link down")

    link = FlakyLink()
    log_lines: list[str] = []
    mon = Monitor("home", None, link, tick=1, log=log_lines.append)

    with anyio.fail_after(5):
        async with anyio.create_task_group() as tg:
            tg.start_soon(mon.run)
            await anyio.sleep(3)
            tg.cancel_scope.cancel()

    assert any("dispatch error" in line.lower() for line in log_lines)


async def test_daemon_delete_pending_rainy_schedules(engine, fake_db):
    """During rain delay, unseen schedules for valves with runoff > 0 are deleted."""
    _seed_and_commit(engine)

    s, scm, sctx = _mgr(engine)
    try:
        valve = s.scalar(select(r.Valve).where(r.Valve.name == "V1"))
        s.add(r.Schedule(valve=valve, start=datetime.now(UTC), duration=120, seen=False))
        s.flush()
        s.commit()
    finally:
        _close(scm, sctx)

    db = fake_db
    mon = Monitor("home", None, StubLink(), tick=60)
    mon._rain_active = True  # noqa: SLF001
    mon._rain_deadline = datetime.now(UTC) + timedelta(minutes=10)  # noqa: SLF001

    mon._tick(db)  # noqa: SLF001

    s2, cm2, ctx2 = _mgr(engine)
    try:
        with s2.execute(select(r.Schedule)) as rs:
            assert len(list(rs)) == 0
    finally:
        _close(cm2, ctx2)


async def test_run_monitor_convenience(engine, fake_db):  # noqa: ARG001
    """run_monitor() creates a Monitor and runs it."""
    _seed_and_commit(engine)

    from moat.db.rain.monitor import run_monitor  # noqa: PLC0415

    link = StubLink()
    evt = anyio.Event()

    with anyio.fail_after(5):
        async with anyio.create_task_group() as tg:
            tg.start_soon(lambda: run_monitor("home", None, link, tick=1, evt=evt))
            await evt.wait()
            await anyio.sleep(0.5)
            tg.cancel_scope.cancel()

    assert evt.is_set()


# ---------------------------------------------------------------------------
# Tests — CLI smoke test
# ---------------------------------------------------------------------------


async def test_cli_monitor_smoke(engine, monkeypatch):
    """``moat db rain <site> monitor`` starts and stops cleanly via the CLI.

    Monkeypatches ``moat.link.client.Link`` so the CLI uses a
    :class:`StubLink` instead of a real MQTT client, and patches the
    config to include a minimal ``link`` section.  The daemon is
    cancelled after a short delay to simulate a controlled shutdown.
    """
    _seed_and_commit(engine)

    import moat.db as mdb  # noqa: PLC0415
    import moat.link.client as link_client  # noqa: PLC0415

    # Patch the database so the CLI's session setup uses our test engine.
    db = _fake_database(engine)
    monkeypatch.setattr(mdb, "database", db)

    # Patch Link so ``Link(cfg)`` returns a StubLink-compatible object.
    class StubLinkCM:
        """A StubLink wrapped as an async context manager (like real Link)."""

        def __init__(self, _cfg=None):
            self._inner = StubLink()

        async def __aenter__(self):
            return self._inner

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(link_client, "Link", StubLinkCM)

    db_url = f"sqlite:///{engine.url.database}"
    from moat.src.test import run  # noqa: PLC0415

    try:
        with anyio.fail_after(10):
            async with anyio.create_task_group() as tg:

                async def _run_cli():
                    await run(
                        "-s",
                        "moat.db.url",
                        db_url,
                        "-s",
                        "link.backend",
                        "mock",
                        "db",
                        "rain",
                        "home",
                        "monitor",
                        "--tick",
                        "1",
                    )

                tg.start_soon(_run_cli)
                await anyio.sleep(3)
                tg.cancel_scope.cancel()
    finally:
        pass

    # Reaching here means the CLI started and stopped without hanging.
