(moat-db-rain)=
# DB: Irrigation (Rain)

The `moat.db.rain` subsystem provides irrigation scheduling and
monitoring for MoaT. It manages every persistent entity of an
irrigation system — sites, controllers, valves, feeds, weather sensors,
groups, environmental effects, day and day-range definitions, overrides,
and the generated watering schedule — and drives the live system from a
per-site daemon.

The subsystem was migrated from the legacy Django `rainman` app to a
SQLAlchemy + Alembic submodule, following the conventions already
established by `moat.db.box`, `moat.db.thing`, and `moat.db.label`. All
tables share one physical database and carry a `rain_` prefix to avoid
collisions. The schema is created by a single Alembic revision chained
onto the shared `moat/db/alembic/` tree owned by `moat-db`.

For the full analysis of the legacy app, the locked design decisions,
the schema, and the phased implementation record, see
[MIGRATION.md](MIGRATION.md).

```{include} ../../packaging/moat-db-rain/README.md
:start-after: % start main
:end-before: % end main
```

## Module overview

The rain subsystem is organised into a small set of focused modules
under `moat/db/rain/`:

- **`range`** (`moat.db.rain.range`) — interval-algebra primitives,
  ported near-verbatim from the legacy `rainman/utils.py`. Pure iterators
  over half-open `(start, length)` intervals (`range_union`,
  `range_intersection`, `range_invert`, `range_coalesce`) with no ORM
  dependency. Every other module builds on this sorted-interval protocol.
- **`model`** (`moat.db.rain.model`) — the SQLAlchemy declarations for
  the `rain_*` schema: sites, controllers, valves, feeds, the
  polymorphic `Sensor` table, groups, env groups, day/day-range
  registries, overrides, and the generated `Schedule`/`Level`/
  `History`/`Log` rows. Duration columns store integer seconds and
  expose `timedelta` properties; MoaT-link addresses use `moat.lib.path`
  columns.
- **`engine`** (`moat.db.rain.engine`) — the scheduler engine. Each
  entity's permitted-watering intervals are expressed as a
  `_range(start, end)` generator rewritten from Django ORM queries to
  SQLAlchemy; the `valve_range` orchestrator intersects group-day
  ranges, overrides, controller capacity, and feed capacity.
  `generate_schedule()` plans watering slots until each valve's level
  deficit is met, and `recalculate()` replays `History` rows to rebuild
  `Level` rows. Both are plain synchronous functions over a
  caller-supplied session.
- **`monitor`** (`moat.db.rain.monitor`) — the long-running daemon,
  porting the legacy `runschedule` command to anyio + moat.link. It
  subscribes to weather sensors, tracks rain-delay, periodically calls
  the scheduler engine, dispatches pending valve commands to
  controllers via moat-link RPC, and maintains level / history / log
  rows. Launched by `moat db rain <SITE> monitor` and run as a
  `Type=notify` systemd service.
- **`cmds`** (`moat.db.rain.cmds`) — the command-line interface, one
  file per entity (`controller`, `valve`, `feed`, `sensor`, `group`,
  `env`, `day`, `dayrange`, `override`, `schedule`, `history`) plus the
  `gen`, `recalc`, and `monitor` verbs. Reached as
  `moat db rain <SITE> <verb>`; adding an entity is a new `cmds/` file
  with no per-entity edits to the thin `_main.py` group.

## Manual

```{toctree}
:maxdepth: 2
:hidden:

MIGRATION
api
```
