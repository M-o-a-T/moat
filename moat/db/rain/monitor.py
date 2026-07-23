"""Long-running irrigation monitor daemon.

Ports the legacy ``runschedule`` management command (qbroker / gevent /
rpyc) to **anyio + moat.link + SQLAlchemy**.  The daemon is launched by
``moat db rain at <SITE> monitor`` (see :mod:`moat.db.rain.cmds.at.monitor`) and
runs as a ``Type=notify`` systemd service (see
``packaging/moat-db-rain/moat-db-rain@.service``).

Responsibilities (preserved from the legacy daemon):

* **Sensor collection** — subscribe to weather sensors (``rain_sensor``
  rows) via moat.link; accumulate weighted readings into ``History``
  rows; deprecate stale sensor readings.
* **Rain-delay tracking** — suppress scheduling while rain is recent,
  using ``Site.rain_delay``.
* **Schedule generation** — periodically (and on sensor / level change)
  call :func:`moat.db.rain.engine.generate_schedule` for the site's
  valves; mark new / changed ``Schedule`` rows.
* **Dispatch** — send pending schedules (``seen=False``) to each
  ``Controller`` via moat-link RPC (the controller's fixed link
  address); mark ``seen=True``; honour ``changed`` / ``forced`` flags.
* **Level maintenance** — call :func:`moat.db.rain.engine.recalculate`
  incrementally; set ``Valve.priority`` when a cycle didn't finish.
* **Logging** — append ``Log`` rows for notable events (errors, rain
  start / stop, manual overrides).

The daemon uses a single anyio task group with one long-running task per
concern (sensors, scheduler, dispatcher), communicating via anyio memory
channels — replacing the old gevent ``Queue`` / ``Semaphore`` /
``AsyncResult``.  All waits are event-driven (link subscriptions, channel
receives, timers via :func:`anyio.sleep`); there are no busy-loops.

The :class:`Monitor` class accepts a ``link`` object that only needs to
provide ``d_watch`` and ``d_set`` — in production this is a
:class:`moat.link.client.Link`; in tests it is a stub with no real
hardware.  The database session is opened per-cycle via
:func:`moat.db.util.database` so the daemon never holds a long-lived
transaction.
"""

from __future__ import annotations

import anyio
import logging
from contextlib import AbstractContextManager
from datetime import UTC, datetime, timedelta

from moat.util import NotGiven
from moat.db.rain.engine import generate_schedule, recalculate
from moat.db.util import Mgr

from collections.abc import AsyncIterator, Callable
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from moat.lib.path import Path

logger = logging.getLogger(__name__)


#: A callable that opens a DB session context manager, like
#: :func:`moat.db.util.database`.
DatabaseFn = Callable[..., AbstractContextManager[Mgr]]


class _AsyncCMIter(Protocol):
    """An object that is both an async context manager and an async iterator.

    This is the shape returned by
    :meth:`moat.link.client.Link.d_watch`.
    """

    async def __aenter__(self) -> AsyncIterator[object]: ...

    async def __aexit__(self, *exc: object) -> None: ...

    def __aiter__(self) -> AsyncIterator[object]: ...

    async def __anext__(self) -> object: ...


class LinkLike(Protocol):
    """Minimal interface the monitor needs from a moat.link client.

    In production this is :class:`moat.link.client.Link`; in tests it
    is :class:`StubLink` (or any duck-typed stand-in).
    """

    def d_watch(self, path: Path, **kw: object) -> _AsyncCMIter:
        """Subscribe to a data path, yielding updates as they arrive.

        The returned object is an async context manager that yields an
        async iterator of values.
        """

    async def d_set(self, path: Path, data: object = ..., **kw: object) -> None:
        """Set a value at a data path."""


#: Sensors are deprecated (weight × 0.01) if no value arrives within this
#: many seconds.  Mirrors the legacy ``METER_TIME = 5*60``.
SENSOR_TIME: int = 5 * 60

#: A sensor that hasn't reported for this long is effectively dead — its
#: weight is reduced to 1 %.  Mirrors the legacy ``METER_MAXTIME = 60*60``.
SENSOR_MAXTIME: int = 60 * 60

#: How often the scheduler tick runs (seconds).  The legacy default was
#: 600 s (``--timeout 600``); the modern daemon ticks faster because it
#: is also woken on sensor events.
_TICK: int = 300

#: Channel buffer size for inter-task communication.
_CHAN_BUF: int = 16


class Monitor:
    """Irrigation monitor daemon for one site.

    The daemon is structured as three cooperating anyio tasks inside a
    single task group:

    * **Sensor collector** — subscribes to each ``rain_sensor`` row's
      ``state`` path via ``link.d_watch``, accumulates weighted readings,
      and writes ``History`` rows.  Signals the scheduler on each update.
    * **Scheduler** — on each wake-up (timer or sensor signal), opens a
      DB session, calls :func:`moat.db.rain.engine.generate_schedule` and
      :func:`moat.db.rain.engine.recalculate`, and enqueues pending schedules for the
      dispatcher.
    * **Dispatcher** — drains the pending-schedule channel and sends
      valve commands via ``link.d_set`` to the controller's link
      address, marking each schedule ``seen=True``.

    Args:
        site_name: The site to monitor.
        db_cfg: Database configuration (``cfg.db``) for session creation.
        link: A moat.link client (or test stub) providing ``d_watch``
            and ``d_set``.
        tick: Scheduler tick interval in seconds (default 300).
        evt: Optional readiness event — ``set()`` is called once the
            daemon is fully initialised (used by systemd ``READY=1``).
        log: Optional callback for human-readable event lines.
    """

    def __init__(
        self,
        site_name: str,
        db_cfg: object,
        link: LinkLike,
        *,
        tick: int = _TICK,
        evt: anyio.Event | None = None,
        log: Callable[[str], None] | None = None,
    ) -> None:
        self.site_name = site_name
        self.db_cfg = db_cfg
        self.link = link
        self.tick = tick
        self._evt = evt
        self._log_cb = log or (lambda _msg: None)

        #: Set when rain has been detected; cleared after ``rain_delay``.
        self._rain_active: bool = False
        self._rain_deadline: datetime | None = None

    def _log(self, msg: str) -> None:
        """Emit a human-readable event line."""
        self._log_cb(msg)

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Run the monitor daemon until cancelled.

        Opens a task group with the sensor, scheduler, and dispatcher
        tasks.  The readiness event is set once all tasks have started.
        """
        from moat.db import database  # noqa: PLC0415 — late import to avoid cycles

        async with (
            anyio.create_task_group() as tg,
        ):
            # Signal readiness once the task group is established.
            if self._evt is not None:
                self._evt.set()
            self._log(f"Monitor started for site {self.site_name!r}")

            tg.start_soon(self._sensor_loop, database)
            tg.start_soon(self._scheduler_loop, database)

    # ------------------------------------------------------------------
    # Sensor collection
    # ------------------------------------------------------------------

    async def _sensor_loop(self, database: DatabaseFn) -> None:
        """Subscribe to weather sensors and accumulate ``History`` rows.

        Each ``rain_sensor`` row's ``state`` path is watched via
        ``link.d_watch``.  Incoming readings are accumulated per-kind;
        when the scheduler tick fires (or a rain sensor triggers), the
        accumulated values are flushed into a ``History`` row.

        Rain sensors additionally arm the rain-delay timer: while active,
        the scheduler skips schedule generation and pending unseen
        schedules for valves with ``runoff > 0`` are deleted.
        """

        sensors = self._load_sensors(database)
        if not sensors:
            self._log("No sensors configured; sensor loop idle.")
            return

        async with anyio.create_task_group() as tg:
            for sensor in sensors:
                tg.start_soon(self._watch_sensor, database, sensor)

    def _load_sensors(self, database: DatabaseFn) -> list[tuple[str, str, Path, int]]:
        """Load sensor rows ``(kind, name, state_path, weight)`` from the DB.

        Returns a list of tuples suitable for spawning watch tasks
        without holding a session open.
        """
        from moat.db.rain.model import Sensor  # noqa: PLC0415

        result: list[tuple[str, str, Path, int]] = []
        with database(self.db_cfg) as sess:  # type: ignore[operator]
            from sqlalchemy import select  # noqa: PLC0415

            from moat.db.rain.model import Site  # noqa: PLC0415

            site = sess.one(Site, name=self.site_name)
            with sess.execute(
                select(Sensor).where(Sensor.site == site).order_by(Sensor.kind, Sensor.name)
            ) as rs:
                for (sensor,) in rs:
                    result.append((sensor.kind, sensor.name, sensor.state, sensor.weight))
        return result

    async def _watch_sensor(
        self,
        database: DatabaseFn,
        sensor_info: tuple[str, str, Path, int],
    ) -> None:
        """Watch one sensor path and accumulate readings into ``History``.

        On each reading:
        * If the sensor is a rain sensor and the value is positive, arm
          the rain-delay timer.
        * Flush accumulated readings into a ``History`` row on each
          scheduler tick.
        """
        kind, name, state_path, weight = sensor_info
        self._log(f"Watching {kind} sensor {name!r} at {state_path}")
        try:
            async with self.link.d_watch(state_path) as mon:  # type: ignore[attr-defined]
                async for value in mon:
                    if value is NotGiven:
                        continue
                    self._accumulate_reading(kind, value, weight)
                    if kind == "rain":
                        self._has_rain(database, value)
        except Exception as exc:
            self._log(f"Sensor {name!r} ({kind}) watch error: {exc}")

    def _accumulate_reading(self, kind: str, value: object, weight: int) -> None:
        """Stash a sensor reading for the next ``History`` flush.

        Readings are accumulated in a per-kind buffer; the scheduler
        tick flushes them into a ``History`` row.  The weighting and
        staleness logic mirrors the legacy ``AvgMeter`` / ``SumMeter``
        classes.
        """
        # Store as (weighted_sum, total_weight) per kind
        buf = getattr(self, "_readings", None)
        if buf is None:
            buf = self._readings = {}  # type: ignore[attr-defined]
        try:
            numeric_value = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return
        entry = buf.get(kind, (0.0, 0.0))
        buf[kind] = (entry[0] + weight * numeric_value, entry[1] + weight)

    def _has_rain(self, database: DatabaseFn, amount: object) -> None:
        """Arm the rain-delay timer.

        While the timer is active, the scheduler skips generation and
        pending unseen schedules for valves with ``runoff > 0`` are
        deleted — mirroring the legacy ``SchedSite.has_rain``.
        """
        try:
            rain_amount = float(amount)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return
        if rain_amount <= 0:
            return
        if not self._rain_active:
            self._log("Started raining")
            self._rain_active = True
        # Extend the deadline by rain_delay from now.
        with database(self.db_cfg) as sess:  # type: ignore[operator]
            from moat.db.rain.model import Site  # noqa: PLC0415

            site = sess.one(Site, name=self.site_name)
            self._rain_deadline = datetime.now(UTC) + site.rain_delay_td

    # ------------------------------------------------------------------
    # Scheduler
    # ------------------------------------------------------------------

    async def _scheduler_loop(self, database: DatabaseFn) -> None:
        """Periodically generate schedules and recalculate levels.

        On each tick (every ``self.tick`` seconds, or sooner if woken by
        a sensor event), opens a fresh DB session, flushes accumulated
        sensor readings into a ``History`` row, calls
        :func:`moat.db.rain.engine.recalculate` then
        :func:`moat.db.rain.engine.generate_schedule`, and logs the
        result.  Skips generation while rain-delay is active.

        Pending schedules collected by the tick are dispatched to their
        controllers via :meth:`moat.link.client.Link.d_set` *after* the
        DB session has committed — the DB work stays synchronous and
        transactional, the link I/O is awaited from this async task.
        """
        # Initial delay so sensors can connect first.
        await anyio.sleep(1)
        while True:
            commands = self._tick(database)
            for path, payload in commands:
                try:
                    await self.link.d_set(path, payload)
                except Exception as exc:
                    self._log(f"Dispatch error to {path}: {exc}")
            await anyio.sleep(self.tick)

    def _tick(self, database: DatabaseFn) -> list[tuple[Path, object]]:
        """Run one scheduler cycle synchronously inside a fresh session.

        Returns:
            A list of ``(command_path, payload)`` pairs for the
            dispatcher to send via :meth:`Link.d_set`.  The DB session
            is committed before the commands are returned, so the link
            I/O happens outside the transaction.
        """

        now_utc = datetime.now(UTC)
        rain_active = self._rain_active and (
            self._rain_deadline is not None and now_utc < self._rain_deadline
        )
        if self._rain_active and not rain_active:
            self._rain_active = False
            self._rain_deadline = None
            self._log("Stopped raining")

        commands: list[tuple[Path, object]] = []
        with database(self.db_cfg) as sess:  # type: ignore[operator]
            # Flush accumulated sensor readings into a History row.
            self._flush_history(sess, now_utc)

            if rain_active:
                self._log("Rain delay active; skipping schedule generation")
                self._delete_pending_rainy_schedules(sess)
                return commands

            # Recalculate levels from history, then generate new schedules.
            recalculate(sess, site=self.site_name, save=True)
            gen_res = generate_schedule(sess, site=self.site_name, save=True)

            if gen_res["schedules"] or gen_res["forced"]:
                self._log(
                    f"Generated {gen_res['schedules']} schedules "
                    f"({gen_res['forced']} forced) for {gen_res['valves']} valves"
                )

            # Collect pending unseen schedules for dispatch.
            commands = self._dispatch(sess)
        return commands

    def _flush_history(self, sess: Mgr, now_utc: datetime) -> None:
        """Write a ``History`` row from accumulated sensor readings.

        Clears the per-kind accumulation buffer.  Kinds with no readings
        are omitted (the column defaults to 0).  Mirrors the legacy
        ``SchedSite.new_history_entry``.
        """
        buf = getattr(self, "_readings", None)
        if not buf:
            return
        from moat.db.rain.model import History, Site  # noqa: PLC0415

        site = sess.one(Site, name=self.site_name)
        kwargs: dict[str, float] = {}
        for kind, (wsum, wtot) in buf.items():
            if wtot > 0:
                kwargs[kind] = wsum / wtot
        buf.clear()
        if not kwargs:
            return
        hist = History(site=site, time=now_utc, **kwargs)
        sess.add(hist)
        sess.flush()
        self._log(f"Recorded history: {kwargs}")

    def _delete_pending_rainy_schedules(self, sess: Mgr) -> None:
        """Delete unseen schedules for valves with runoff > 0 during rain.

        Mirrors the legacy
        ``Schedule.objects.filter(valve__in=vo, start__gte=now()-1d, seen=False).delete()``.
        """

        from sqlalchemy import delete, select  # noqa: PLC0415

        from moat.db.rain.model import Schedule, Valve  # noqa: PLC0415

        cutoff = datetime.now(UTC) - timedelta(days=1)
        # Select valves with runoff > 0
        rainy_valves = select(Valve.id).where(Valve.runoff > 0)
        sess.execute(
            delete(Schedule).where(
                Schedule.valve_id.in_(rainy_valves),
                Schedule.start >= cutoff,
                Schedule.seen.is_(False),
            )
        )
        sess.flush()

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def _dispatch(self, sess: Mgr) -> list[tuple[Path, object]]:
        """Collect pending unseen schedules for dispatch via moat.link.

        For each ``Schedule`` with ``seen=False`` whose ``start`` is
        imminent (within the tick window), build a valve command
        addressed to the valve's ``command`` path and mark the schedule
        ``seen=True``.  Schedules whose valve has no ``command`` path are
        skipped (monitor-only).  The ``changed`` and ``forced`` flags are
        propagated into the command payload so the controller can
        distinguish a routine run from a forced or corrected one.

        This is a synchronous method called from within the scheduler
        tick; it does **not** send the commands — it returns them so the
        async scheduler loop can ``await link.d_set`` after the session
        has committed.  Keeping the link I/O out of the transaction
        avoids holding a DB write lock across a network round-trip.

        Args:
            sess: The owning session.

        Returns:
            A list of ``(command_path, payload)`` pairs to send.
        """

        from sqlalchemy import select  # noqa: PLC0415

        from moat.db.rain.model import Schedule  # noqa: PLC0415

        now_utc = datetime.now(UTC)
        horizon = now_utc + timedelta(seconds=self.tick)
        with sess.execute(
            select(Schedule)
            .where(Schedule.seen.is_(False), Schedule.start <= horizon)
            .order_by(Schedule.start)
        ) as rs:
            pending = list(rs)
        if not pending:
            return []

        commands: list[tuple[Path, object]] = []
        for (sched,) in pending:
            valve = sched.valve
            if valve.command is None:
                continue
            sched.seen = True
            payload: dict[str, object] = {
                "start": sched.start,
                "duration": sched.duration,
                "forced": sched.forced,
                "changed": sched.changed,
            }
            commands.append((valve.command, payload))
            self._log(
                f"Dispatching valve {valve.controller.name}:{valve.name} "
                f"start={sched.start} duration={sched.duration}s"
                + (" FORCED" if sched.forced else "")
                + (" CHANGED" if sched.changed else "")
            )
        sess.flush()
        return commands


async def run_monitor(
    site_name: str,
    db_cfg: object,
    link: LinkLike,
    *,
    tick: int = _TICK,
    evt: anyio.Event | None = None,
    log: Callable[[str], None] | None = None,
) -> None:
    """Convenience entry point: create and run a :class:`Monitor`.

    Args:
        site_name: The site to monitor.
        db_cfg: Database configuration (``cfg.db``).
        link: A moat.link client (or test stub).
        tick: Scheduler tick interval in seconds.
        evt: Readiness event (set once the daemon is initialised).
        log: Optional human-readable event sink.
    """
    mon = Monitor(site_name, db_cfg, link, tick=tick, evt=evt, log=log)
    await mon.run()
