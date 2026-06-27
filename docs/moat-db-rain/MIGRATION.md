# Migration Plan: `rainman` (Django) → `moat.db.rain` (SQLAlchemy + Alembic)

This document records the analysis of the legacy Django irrigation app in
`/src/moat-old/irrigation/` and defines how it is rebuilt as the
`moat.db.rain` submodule, following the conventions already established by
`moat.db.box`, `moat.db.thing`, and `moat.db.label`.

Scope: **data model + command-line CRUD + the scheduler engine**, shipped
as one installable sub-package `moat-db-rain` (Python wheel **and** Debian
package). The engine's long-running driver is exposed as
`moat db rain <site> monitor`.

Out of scope (web UI, auth, data import — §11) are filed as beads issues.

---

## 1. Goals & non-goals

Goals:

- Recreate every persistent entity of the old `rainman` Django app as a
  SQLAlchemy ORM model living under `moat.db.rain`.
- Provide an `asyncclick` command-line interface for listing, showing,
  adding, modifying, and deleting each entity, exactly like
  `moat box …` / `moat thing …`, reached as **`moat db rain …`**.
- Port the **scheduler engine**: the interval-algebra utilities
  (`range_union`/`range_intersection`/`range_invert`/`range_coalesce`),
  every entity's `_range(start,end)` generator (rewritten from Django ORM
  queries to SQLAlchemy), and the schedule-generation / level-recalculation
  logic. These live in `moat.db.rain` alongside the models.
- Provide the long-running daemon **`moat db rain <site> monitor`** that
  runs the current schedule, watches weather sensors, talks to controllers
  via MoaT-link, and maintains `Schedule`/`Level`/`History`/`Log` rows.
  (Phased — the daemon lands last; see §10.)
- Manage the schema with the **shared** Alembic tree at
  `moat/db/alembic/` (owned by `moat-db`); rain's tables are added by a
  new revision chained off the then-current head `dd1007d00e262b5c`
  (the new head is `9a3f1c7e4b2d`).
- Ship as `moat-db-rain` with `pyproject.toml`, README, docs, tests, **and
  a `debian/` packaging directory** (wheel + `.deb` + systemd unit),
  mirroring `moat-db-box` for the wheel and `moat-kv-akumuli` for the
  Debian/systemd-daemon side.

Non-goals (deferred — file beads issues, §11):

- Authentication / authorization (`UserForSite`, tied to Django auth).
- The Django web UI, Jinja templates, and admin.
- Importing data from a live `rainman_*` database.
- `genconfig` / `genhabconfig` (emit controller/openHAB config snippets) —
  lower-value generators, deferred after the core engine + monitor work.

---

## 2. Source analysis: the old `rainman` app

The Django app `rainman` (under `/src/moat-old/irrigation/rainman/`)
defines its models in `models/*.py`. The authoritative SQL shape is the
initial migration `migrations/0001_initial_stuff.py`; the model files
contain additional Python behaviour (properties, range algorithms) that
informs column semantics and is ported by the engine (§7).

### 2.1 Entities and their columns

Legend: PK = surrogate `id` (Django AutoField, mirrored by
`moat.db.schema.Base`). "UT" = `unique_together`. Durations were stored as
integer **seconds** in `db_*` columns and exposed as `timedelta` via
properties.

| Entity (old table) | Columns (excluding PK) | UT | Notes |
|---|---|---|---|
| **Site** (`rainman_site`) | `name` str200 uniq, `comment` str200?, `var` str200 uniq?, `host` str200, `port` posint, `db_rate` float (col `rate`), `db_rain_delay` posint (col `rain_delay`) | — | Model file *also* declares `username`/`password`/`virtualhost` (RabbitMQ); the newer migration **dropped** them and reframed `host`/`port` as "MoaT server / RPC port 50005". Dropped per §4.2. |
| **Controller** (`rainman_controller`) | `name` str200, `var` str200 uniq, `comment` str200?, `site` FK→Site, `location` str200, `max_on` int d=3 | (site,name) | |
| **Valve** (`rainman_valve`) | `name` str200, `comment` str200?, `feed` FK→Feed, `controller` FK→Controller, `envgroup` FK→EnvGroup (col `param_group_id`), `location` str200, `var` str200 uniq, `verbose` possmallint d=0, `flow` float, `area` float, `max_level` float d=10, `start_level` float d=8, `stop_level` float d=3, `shade` float d=1, `db_max_run` posint? (col `max_run`), `db_min_delay` posint? (col `min_delay`), `runoff` float d=1, `time` dt idx d=now, `level` float d=0, `priority` bool d=False | (controller,name) | M2M `groups`→Group via `rainman_group_valves`. |
| **Feed** (`rainman_feed`) | `name` str200, `var` str200 uniq?, `comment` str200?, `site` FK→Site, `flow` float? d=10, `db_max_flow_wait` posint (col `max_flow_wait`) d=300, `disabled` bool d=False | (site,name)¹ | Subclasses abstract `Meter` + `RangeMixin`. ¹UT inherited from `Meter`. |
| **Meter** (abstract) | `name` str200; UT (site,name) | — | Base for weather sensors. |
| **WMeter** (abstract) | + `weight` possmallint d=10, `var` str200 uniq | — | Adds MoaT-link var name. |
| **RainMeter/TempMeter/WindMeter/SunMeter** (`rainman_{rain,temp,wind,sun}meter`) | `name`, `weight`, `var`, `site` FK→Site | (site,name) | Four near-identical tables → collapsed per §4.4. |
| **Group** (`rainman_group`) | `name` str200, `site` FK→Site, `comment` str200?, `adj` float? | (site,name) | M2M `days`→DayRange (rel `groups_y`), `xdays`→DayRange (rel `groups_n`), `valves`→Valve (through `rainman_group_valves`). |
| **EnvGroup** (`rainman_paramgroup`) | `name` str200, `comment` str200?, `site` FK→Site, `factor` float d=1.0, `rain` bool d=True | (site,name) | |
| **EnvItem** (`rainman_environmenteffect`) | `group` FK→EnvGroup (col `param_group_id`), `factor` float d=1.0, `temp` float?, `wind` float?, `sun` float? | — | |
| **Day** (`rainman_day`) | `name` str30 uniq | — | Has child `DayTime`s. |
| **DayTime** (`rainman_daytime`) | `descr` str200, `day` FK→Day | (day,descr) | `descr` parsed by `moat.times.time_until` at runtime (§7.4). |
| **DayRange** (`rainman_dayrange`) | `name` str30 uniq, `comment` str200? | — | M2M `days`→Day (rel `ranges`). Intersection of days. |
| **GroupOverride** (`rainman_groupoverride`) | `name` str200?, `group` FK→Group, `allowed` bool d=False, `start` dt idx, `db_duration` posint (col `duration`), `on_level` float?, `off_level` float? | (group,start) | `end = start+duration`. |
| **ValveOverride** (`rainman_valveoverride`) | `name` str200?, `valve` FK→Valve, `running` bool d=False, `start` dt idx, `db_duration` posint (col `duration`), `on_level` float?, `off_level` float? | (valve,start) | |
| **GroupAdjust** (`rainman_groupadjust`) | `group` FK→Group, `start` dt idx, `factor` float | (group,start) | Linearly-interpolated watering multiplier. |
| **Schedule** (`rainman_schedule`) | `valve` FK→Valve, `start` dt idx, `db_duration` posint (col `duration`), `seen` bool, `changed` bool, `forced` bool | (valve,start) | Produced by the scheduler engine. |
| **Level** (`rainman_level`) | `valve` FK→Valve, `time` dt idx, `level` float, `flow` float d=0, `forced` bool d=False | (valve,time) | Historic per-valve water level. |
| **History** (`rainman_history`) | `site` FK→Site, `time` dt idx, `rain` float d=0, `feed` float d=0, `temp` float?, `wind` float?, `sun` float? | (site,time) | Historic per-site weather/water. |
| **Log** (`rainman_log`) | `logger` str200, `timestamp` dt idx d=now, `site` FK→Site, `controller` FK?→Controller, `valve` FK?→Valve, `text` text | — | |
| **UserForSite** (`rainman_userforsite`) | `user` 1:1 DjangoUser, `level` possmallint (0–3), M2M `sites`→Site, M2M `valves`→Valve | — | **Dropped** — §4.6. |

### 2.2 Relationships summary

- Site ◂── FK ── Controller, Feed, Group, EnvGroup, History, Log, Rain/Temp/Wind/SunMeter, UserForSite
- Controller ◂── FK ── Valve, Log
- Feed ◂── FK ── Valve
- EnvGroup ◂── FK ── Valve (col `param_group_id`), EnvItem
- Valve ◂── FK ── Schedule, ValveOverride, Level, Log; M2M ── Group (`rainman_group_valves`)
- Group ── M2M ── DayRange ×2 (`days`/`xdays`); ── M2M ── Valve (same table)
- DayRange ── M2M ── Day
- Day ◂── FK ── DayTime

### 2.3 Behaviour to port (now in scope)

`rainman/utils.py` implements interval algebra (`range_union`/
`range_intersection`/`range_invert`/`range_coalesce`/`StoredIter`/
`RangeMixin`) — pure Python, portable near-verbatim (drop `six`). Each
model's `_range(start,end)` generator expresses when that entity permits
watering; these are Django-ORM-query-heavy and must be rewritten as
SQLAlchemy `select(...).where(...)` queries. The seven management
commands drive the engine:

| Old command | Purpose | New home |
|---|---|---|
| `runschedule` (1416 lines) | Long-running daemon: send pending schedules to controllers, watch rain/meters, update levels/history/logs, respect rain-delay. Built on **qbroker/gevent/rpyc** → port to **anyio + moat.link**. | `moat db rain <site> monitor` (§7.5) |
| `genschedule` | Compute when each valve should run by intersecting all `_range()` constraints + level thresholds; write `Schedule` rows. | engine `generate_schedule()` + `moat db rain <site> gen` (§7.3) |
| `listschedule` | Report the upcoming schedule for valves/controllers/site. | `moat db rain <site|controller|valve> schedule list` |
| `recalculate` | Recompute `Level` rows from `History` (evaporation/rain/runoff math). | engine `recalculate()` + `moat db rain <site> recalc` (§7.3) |
| `addschedule` | Manually add a `Schedule` entry. | `moat rain schedule add` (CRUD, §6.3) |
| `genconfig` / `genhabconfig` | Emit controller / openHAB config snippets. | **Deferred** (§11) |

---

## 3. Destination conventions (learned from `moat.db.{box,thing,label}`)

The three existing submodules are the template. Key conventions:

- **Base class** (`moat/db/schema.py`): `class Base(DeclarativeBase)` with
  `@declared_attr __tablename__ = cls.__name__.lower()` and a surrogate
  `id = Column(Integer, primary_key=True)`. Provides `dump()` (returns a
  dict, skips `id`/`*_id`) and `apply(**kw)` (sets attrs, treating
  `moat.util.NotGiven` as "leave unchanged").
- **Two-file model split** to break import cycles:
  - `model.py` — pure SQLAlchemy declarations (columns, FKs,
    self-contained relationships). Cross-submodule relationships are
    declared under `if TYPE_CHECKING:` only.
  - `model_.py` — imported *after* all `model.py`s; monkeypatches the
    cross-submodule `relationship()`s onto the classes and installs the
    rich `apply()` methods that resolve FK targets **by name** via
    `sess.one(Table, name=...)` using `moat.db.util.session` (a
    `ContextVar`).
  - **Rain diverges** (§4.10): it has no cross-submodule relationships,
    so `model_.py` is a documented stub and the `apply()` methods are
    real method overrides in `model.py` — no `cast(Any, …)` monkeypatch,
    per the AGENTS.md no-cast policy.
- **Schema registration**: `moat/db/_cfg.yaml` holds the master `schemas:`
  list (e.g. `moat.db.box.model`, then `moat.db.box.model_`).
  `moat/db/util.py::load()` imports each listed module so SQLAlchemy
  registers them on the shared `Base.metadata`. Submodule `__init__.py`
  calls `CfgStore.with_(__name__)` to load any local `_cfg.yaml`.
- **Sessions**: `moat.db.util.database(cfg)` is a context manager yielding
  a `Mgr` wrapping a SQLAlchemy session, bound to the `session` ContextVar.
  SQLite connections get `PRAGMA foreign_keys=ON` automatically.
- **Alembic**: one shared env at `moat/db/alembic/` driven by
  `moat.db.util.alembic_cfg()`. Revisions chain linearly; current head is
  `dd1007d00e262b5c`. `moat db migrate rev` autogenerates off the live
  metadata; `moat db init` stamps `head`; `moat db migrate update` upgrades.
- **CLI loading** (`moat.lib.run.Loader`): `moat db` is a `Loader` with
  `prefix="moat.db"` (so `ext_pre="moat.db"`, `ext_post="_main.cli"`).
  Its `list_commands` resolves each subcommand via
  `load_ext("moat.db","<name>","_main","cli")`, i.e.
  `moat.db.<name>._main.cli` — **not** the `cli` attribute on the
  subpackage. Thus rain is discovered as `moat.db.rain._main.cli`,
  exactly like `box`/`thing`/`label`; `moat/db/rain/__init__.py` must
  **not** export `cli` (it is docstring + `CfgStore.with_(__name__)`
  only), otherwise `moat db --help` lists `rain` twice (the `sub_pre`
  scan would also find `moat.db.rain.cli`). (`box`/`thing`/`label` are
  additionally reachable as top-level `moat box` etc.; rain is
  `moat db rain` only.) Confirmed by the Phase-1 smoke test.
- **CLI body** (thin group + `cmds/`, cf. `moat.link._main` /
  `moat.link.cmd`): `_main.py` defines only the top-level `cli` group
  via `@load_subgroup(sub_pre="moat.db.rain.cmds", sub_post="cli",
  ext_pre="moat.db.rain", ext_post="_main.cli")`. That group opens a
  `database(cfg)` session + `begin()` via `ctx.with_resource(...)` and
  sets `obj.session`; it discovers its subcommands by scanning the
  `moat.db.rain.cmds.*` namespace and importing each
  `cmds/<name>.py::cli` (a `@click.group` with `show`/`add`/`set`/
  `delete`, or a leaf command). Adding an entity is just a new `cmds/`
  file — the thin `_main.py` needs no per-entity edits. Options use
  `option_ng(...)` (allows `--name -` sentinel meaning "clear"); output
  via `moat.util.yprint`. Everything lives under `moat.db`; **no
  `moat.rain` top-level module is created**. The group takes a positional
  `<SITE>` *before* the verb — `moat db rain <SITE> <verb>` — the
  established MoaT pattern (cf. `mt link wago NAME <verb>`): the group is
  declared `invoke_without_command=True` with `@click.argument("site")`,
  sets `obj.site_name`, and `moat db rain -` lists sites / `moat db rain
  <SITE>` shows one. This is implemented in the Phase-1 scaffold (proven
  by an integration test: `@load_subgroup` + positional +
  `invoke_without_command` + `cmds/` discovery disambiguate correctly),
  not deferred. A separate `moat rain …` top-level alias remains out of
  scope.
- **Packaging (wheel)**: `packaging/moat-db-<x>/` with `pyproject.toml`
  (deps include `moat-db ~= 0.2.7`, `moat-lib-run`, `asyncclick`),
  `README.md` using `% start synopsis` / `% start main` / `% end …`
  markers, and `LICENSE.txt`. `src/` is auto-populated and git-ignored.
- **Packaging (Debian)**: a `debian/` dir (see §9) — present on
  `moat-kv-*` / `moat-lib-codec` / `moat` but **not yet** on the existing
  `moat-db*` packages.
- **Docs**: `docs/moat-db-<x>/index.md` includes the packaging README's
  `main` block, plus `api.rst`; linked from `docs/moat-db/index.md`.
- **Typing**: `ty` is the checker; new dirs must be added to
  `[tool.ty.src] include` in the root `pyproject.toml`. Comprehensive
  typing, no `type:ignore`/`Any`/casts unless provably unavoidable.

---

## 4. Design decisions (locked)

These were proposed and ACKed; they are no longer open.

### 4.1 Table naming — prefix with `rain_`

All rain tables share one physical database with `box`/`thing`/`label`.
Generic names like `site`, `group`, `schedule`, `level`, `history`,
`log`, `feed` would collide (or soon collide) with other submodules.
Override `__tablename__` per class with a `rain_` prefix
(e.g. `rain_site`, `rain_valve`, `rain_schedule`, `rain_group_valves`),
exactly as the old code used `db_table="rainman_*"`. Deliberately diverges
from `Base`'s auto-lowercase default.

### 4.2 Site: drop broker/connection fields

The old `Site` carried RabbitMQ / "MoaT server" connection params.
Connection configuration belongs in MoaT's YAML config / link setup, not
in a per-row DB column. `rain_site` keeps only `name`, `comment`,
`rate` (mm/day, float), `rain_delay` (seconds, int). Drops
`host`/`port`/`username`/`password`/`virtualhost`.

### 4.3 Durations — integer seconds + `timedelta` property

Store integer seconds in a plain `Integer` column named without the
`db_` prefix (`max_run`, `min_delay`, `duration`, `max_flow_wait`,
`rain_delay`), and expose a Python `@property` named `<col>_td` returning
`timedelta(seconds=…)` (e.g. `Site.rain_delay_td`, `Feed.max_flow_wait_td`).
The column keeps the plain name so `Base.dump()` emits raw seconds; the
`_td` sibling is for Python-side use by the engine/monitor. Nullable
where the original was nullable. Avoids `Interval`/driver quirks on
SQLite and matches the legacy data shape.

### 4.4 Weather sensors — one polymorphic `Sensor` table

Collapse the four structurally-identical legacy tables
`RainMeter`/`TempMeter`/`WindMeter`/`SunMeter` into a single `rain_sensor`
table with a `kind` discriminator column (`"rain"|"temp"|"wind"|"sun"`,
short `String` — not a Python `Enum`, to stay simple). Unique constraint
`(site, kind, name)`. `Feed` remains its own table (`rain_feed`) since
its columns differ materially.

### 4.5 Link paths — `moat.lib.path.Path` columns

Every column that names a MoaT-link address is a
:class:`moat.lib.path.Path` in Python and a `VARCHAR(200)` in SQL,
mediated by a small `PathType(TypeDecorator[Path])` declared atop
`model.py` (bind → `str(path)`, load → `Path.from_str(s)`). The empty
path serialises to `":""`; a nullable column maps `None` ↔ SQL `NULL`
(SQLite/Postgres allow multiple NULLs under a unique constraint, so
`unique=True, nullable=True` is preserved where the original was).

The link roles, reflecting how each entity talks to MoaT-link:

| Column | Was | Now |
|---|---|---|
| `Sensor.state` | `Sensor.var` (the subscribed monitor var) | renamed — the sensor's read endpoint |
| `Valve.command` | `Valve.var` ("name of this output") | renamed — the valve's write endpoint (`nullable`) |
| `Valve.state` | — | new — the valve's read/feedback endpoint (`nullable`, unique) |
| `Feed.flow_monitor` | `Feed.var` (the flow meter's monitor name) | renamed — a pointer to the monitoring sensor's path |

`Site.var` and `Controller.var` are **dropped**: a site and its
controllers have fixed addresses in moat.link, not per-row DB columns.

Both `Valve.command` and `Valve.state` are `nullable` and `unique`:
some valves can be monitored but not controlled (state set, command
absent), others controlled but lacking feedback (command set, state
absent). They are distinct columns — `state` does not implicitly track
`command`. Multiple `NULL`s coexist under a unique constraint, so any
combination of presence/absence is allowed. `Sensor.state` remains
mandatory (a sensor with nothing to read is meaningless).

### 4.6 Drop `UserForSite` (auth deferred)

`UserForSite` is welded to Django's auth user model and gates web access.
Omit entirely. Re-introducing access control is a later, cross-cutting
concern (beads epic, §11).

### 4.7 Cascades

Mirror Django's default `on_delete=CASCADE` for all FKs: declare
`ForeignKey("...", ondelete="CASCADE", name="fk_<local>_<remote>")` and
rely on the `PRAGMA foreign_keys=ON` set by
`moat.db.util.set_sqlite_pragma`. Relationships use the default SA
cascade (do *not* add `cascade="delete"`, let the DB do it) **and** set
`passive_deletes=True` on the collection side, so SQLAlchemy does not
pre-empt the DB by NULLing child FKs (which would violate the NOT NULL
FK). Deleting a parent that has children *already loaded* in the session
would still trip that NULL — so one-shot `delete` commands load only the
parent (the collections are lazy) and let `ON DELETE CASCADE` remove the
rows. (Production MariaDB enforces FKs natively; the sqlite pragma path
is for dev/test — `set_sqlite_pragma` was corrected in Phase 2 to
actually detect sqlite, which it previously did not.)

### 4.8 Many-to-many association tables

Define explicit `Table` objects on `Base.metadata` (cf. `boxtyp_tree`):

| Association table | Links | Note |
|---|---|---|
| `rain_group_valves` | Group ↔ Valve | replaces `rainman_group_valves` |
| `rain_group_days` | Group → DayRange (`days`) | `related_name=groups_y` |
| `rain_group_xdays` | Group → DayRange (`xdays`) | `related_name=groups_n` |
| `rain_dayrange_days` | DayRange ↔ Day | |

### 4.9 Schema registration — extend the central list

Append `moat.db.rain.model` and `moat.db.rain.model_` to the `schemas:`
list in `moat/db/_cfg.yaml` (precedent: that file already lists
`box`/`thing`/`label`, which live in separate packages). `moat/db/rain/
__init__.py` calls `CfgStore.with_(__name__)`. No separate `_cfg.yaml`
needed initially. (A cleaner per-submodule `_cfg.yaml` refactor is filed
as a follow-up, §11.)

### 4.10 `apply()` — placement and FK resolution

**Placement.** box/thing/label install `apply()` by monkeypatching in
`model_.py` (`Cls.apply = cast(Any, fn)`), because their `apply()`
references *other submodules'* entities for FK lookups, which would
import-cycle from `model.py`. Rain's relationships are all intra-package,
so there is no cycle to break: `apply()` is therefore defined as **real
method overrides directly on the classes in `model.py`**. This was
verified empirically — `ty` rejects the bare monkeypatch (`sensor_apply`
is "not assignable to attribute `apply` of type `def apply(self, **kw)`")
but accepts the genuine override, so the `cast(Any, …)` that AGENTS.md
discourages is genuinely unnecessary here. `model_.py` stays a stub that
documents why it is empty.

**FK resolution convention** (shapes Phase 6's CLI):

- Parents uniquely identifiable by name within the site — `Site`, `Day`,
  `DayRange` (global), and `EnvGroup`/`Feed`/`Controller`/`Group`/`Sensor`
  (`(site, name)`) — are passed to `apply()` **by name** and resolved with
  `sess.one(Parent, site=<site_obj>, name=…)` (faithful to box/thing).
  Site-scoped entities take a `site=` name argument as the scope anchor
  (derived from an already-linked parent when omitted on update).
- `Valve` has a **compound key** `(controller, name)`, so it is **not**
  name-resolvable within a site. Entities that parent a valve
  (`Schedule`, `ValveOverride`, `Level`, `Log.valve`, `Group.valves`)
  receive the `Valve` **object**; the CLI resolves it via controller+name.
- Path columns (`Sensor.state`, `Valve.command`/`state`, `Feed.flow_monitor`)
  take a **dotted string**, parsed with `Path.from_str`; `None` or `"-"`
  clears a nullable one (a required one rejects clearing).
- M2M collections take name-lists with a `-` prefix for removal
  (box/thing convention), except `Group.valves` which takes `Valve` objects
  (compound key again).
- Plain scalars flow through `Base.apply(**kw)`. `NotGiven` (Ellipsis)
  means "leave unchanged"; `None`/`"-"` means "clear" where nullable.

Lookups run inside `sess.no_autoflush` so a half-built row is not flushed
mid-`apply`.

---

## 5. Target file tree

```
moat/db/rain/
├── __init__.py        # "MoaT irrigation database module."
│                      #   CfgStore.with_(__name__) only; NO `cli` export — discovery is via
│                      #   `moat.db.rain._main.cli` (ext_pre), cf. box/label/thing
├── model.py           # SQLAlchemy declarations (all rain_* tables/classes)
├── model_.py          # stub: rain has no cross-submodule relationships; apply() is in model.py (§4.10)
├── range.py           # interval algebra: range_union/intersection/invert/coalesce, StoredIter, RangeMixin  (§7.1)
├── engine.py          # _range() ports + generate_schedule() + recalculate()  (§7.2–7.3)
├── monitor.py         # daemon run-loop impl behind `moat db rain <site> monitor`  (§7.5)
├── _main.py           # thin top-level `cli` group: @load_subgroup(sub_pre="moat.db.rain.cmds",
│                      #   sub_post="cli", ext_pre="moat.db.rain", ext_post="_main.cli",
│                      #   invoke_without_command=True) + @click.argument("site")  (wago pattern);
│                      #   opens `database(cfg)`+begin(), sets obj.session+obj.site_name;
│                      #   `moat db rain -` lists sites, `moat db rain <SITE>` shows one (Phase 2);
└── cmds/              # one file per subcommand, each exporting `cli` (Loader-discovered)
    ├── __init__.py    # "Sub-command processing here."  (cf. moat.link.cmd.__init__)
    ├── add.py         # `moat db rain <SITE> add`        (create site; wago-style verb)
    ├── set.py          # `moat db rain <SITE> set`        (modify site)
    ├── delete.py       # `moat db rain <SITE> delete`     (delete site)
    ├── controller.py   # `moat db rain <SITE> controller {show,add,set,delete}`
    ├── valve.py        # `moat db rain <SITE> valve {…}`
    ├── feed.py         # `moat db rain <SITE> feed {…}`
    ├── sensor.py       # `moat db rain <SITE> sensor {…}`  # --kind rain|temp|wind|sun
    ├── group.py        # `moat db rain <SITE> group {…}`  # +/-days, +/-xdays, +/-valves
    ├── env.py          # `moat db rain <SITE> env {…}`    # envgroup + nested item
    ├── day.py          # `moat db rain <SITE> day {…}`    # day + nested time / range
    ├── override.py     # `moat db rain <SITE> override {group,valve,adjust}`
    ├── schedule.py     # `moat db rain <SITE> schedule {show,add,set,delete,list}`  # list≈listschedule
    ├── history.py      # `moat db rain <SITE> history {level,hist,log}`
    ├── gen.py          # `moat db rain <SITE> gen`        (old genschedule; §7.3)
    ├── recalc.py       # `moat db rain <SITE> recalc`     (old recalculate; §7.3)
    └── monitor.py      # `moat db rain <SITE> monitor`    (old runschedule; §7.5)

packaging/moat-db-rain/
├── pyproject.toml     # name=moat-db-rain; deps: moat-db ~=0.2.7, moat-lib-run,
│                      #   moat-link ~=0.2, asyncclick, moat-util, anyio
├── README.md          # % start synopsis / % start main markers
├── LICENSE.txt        # copied from packaging/moat-db-box/LICENSE.txt
├── moat-db-rain@.service  # systemd template (packaging root); `rules` copies it into debian/
├── debian/            # Debian packaging (§9)
│   ├── control
│   ├── rules          # `override_dh_auto_install` copies the .service into debian/
│   ├── changelog
│   ├── source/format
│   ├── py3dist-overrides
│   └── .gitignore     # ignores the built copy: /*.service, /moat-db-rain, …
│                      # (src/ auto-populated, git-ignored; no .install — dh_installsystemd
│                      #  auto-ships the .service, cf. moat-kv-akumuli)

docs/moat-db-rain/
├── index.md           # mirrors docs/moat-db-box/index.md; includes README main block
├── api.rst            # sphinx autodoc stub
└── MIGRATION.md       # this file

tests/moat_db_rain/
├── test_model.py      # CRUD per entity, FK-by-name, M2M add/remove, unique-violations
├── test_range.py      # interval-algebra port parity vs. old utils.py cases
├── test_engine.py     # generate_schedule / recalculate on a seeded temp sqlite DB
└── test_monitor.py   # daemon loop with a stubbed moat.link (no real hardware)
```

Plus edits to existing files (§6.4).

---

## 6. Entity → table mapping

### 6.1 Core entities

| New class | Table | Key columns (beyond PK) | FKs / relations |
|---|---|---|---|
| `Site` | `rain_site` | `name` uniq, `comment`?, `rate` float, `rain_delay` int(sec) | ← controllers, feeds, groups, envgroups, sensors, histories, logs |
| `Controller` | `rain_controller` | `name`, `comment`?, `location`, `max_on` int d=3 | `site`→Site; → valves, logs. UQ(site,name) |
| `Valve` | `rain_valve` | `name`, `comment`?, `location`, `command` Path? uniq, `state` Path? uniq, `verbose` d=0, `flow`, `area`, `max_level` d=10, `start_level` d=8, `stop_level` d=3, `shade` d=1, `max_run`?(sec), `min_delay`?(sec), `runoff` d=1, `time` dt idx d=now, `level` d=0, `priority` bool | `feed`→Feed, `controller`→Controller, `envgroup`→EnvGroup; M2M `groups`↔Group; → schedules, overrides, levels, logs. UQ(controller,name) |
| `Feed` | `rain_feed` | `name`, `flow_monitor` Path uniq?, `comment`?, `flow`? d=10, `max_flow_wait`(sec) d=300, `disabled` bool | `site`→Site; → valves. UQ(site,name) |
| `Sensor` | `rain_sensor` | `kind` str(rain/temp/wind/sun), `name`, `state` Path uniq, `weight` d=10 | `site`→Site. UQ(site,kind,name) |
| `Group` | `rain_group` | `name`, `comment`?, `adj`? | `site`→Site; M2M `days`/`xdays`↔DayRange; M2M `valves`↔Valve. UQ(site,name) |
| `EnvGroup` | `rain_envgroup` | `name`, `comment`?, `factor` d=1.0, `rain` bool d=True | `site`→Site; → items, valves. UQ(site,name) |
| `EnvItem` | `rain_envitem` | `factor` d=1.0, `temp`?, `wind`?, `sun`? | `group`→EnvGroup |
| `Day` | `rain_day` | `name` str30 uniq | → times, ranges (M2M↔DayRange) |
| `DayTime` | `rain_daytime` | `descr` str200 | `day`→Day. UQ(day,descr) |
| `DayRange` | `rain_dayrange` | `name` str30 uniq, `comment`? | M2M `days`↔Day; back `groups`/`xgroups`↔Group (via `Group.days`/`Group.xdays`) |
| `GroupOverride` | `rain_group_override` | `name`?, `allowed` bool, `start` dt idx, `duration`(sec), `on_level`?, `off_level`? | `group`→Group. UQ(group,start) |
| `ValveOverride` | `rain_valve_override` | `name`?, `running` bool, `start` dt idx, `duration`(sec), `on_level`?, `off_level`? | `valve`→Valve. UQ(valve,start) |
| `GroupAdjust` | `rain_group_adjust` | `start` dt idx, `factor` float | `group`→Group. UQ(group,start) |
| `Schedule` | `rain_schedule` | `start` dt idx, `duration`(sec), `seen`/`changed`/`forced` bool | `valve`→Valve. UQ(valve,start) |
| `Level` | `rain_level` | `time` dt idx, `level` float, `flow` d=0, `forced` bool | `valve`→Valve. UQ(valve,time) |
| `History` | `rain_history` | `time` dt idx, `rain` d=0, `feed` d=0, `temp`?, `wind`?, `sun`? | `site`→Site. UQ(site,time) |
| `Log` | `rain_log` | `logger` str200, `timestamp` dt idx d=now, `text` text | `site`→Site, `controller`?→Controller, `valve`?→Valve |

### 6.2 Association tables

`rain_group_valves`, `rain_group_days`, `rain_group_xdays`,
`rain_dayrange_days` — each with composite PK `(parent_id, child_id)` and
named FK constraints (`fk_<table>_<role>`).

### 6.3 CLI surface (`moat db rain …`)

The thin top-level group (`_main.py::cli`) opens a DB
session/transaction (cf. `moat box`), sets `obj.session` **and
`obj.site_name`**, and takes a positional `<SITE>` *before* the verb —
`moat db rain <SITE> <verb>` — the established MoaT pattern (cf.
`mt link wago NAME <verb>`): declared `invoke_without_command=True`
with `@click.argument("site")`, so `moat db rain -` lists sites and
`moat db rain <SITE>` shows one (these queries land in Phase 2 with the
`Site` model; the scaffold just records `obj.site_name`). It discovers
its subcommands from `moat/db/rain/cmds/<name>.py` — each file exports a
`cli` (a `@click.group` with `show`/`add`/`set`/`delete`, or a leaf
command) — via `@load_subgroup(sub_pre="moat.db.rain.cmds",
sub_post="cli", ext_pre="moat.db.rain", ext_post="_main.cli")`, the
`moat.link._main` / `moat.link.cmd` pattern.
This combination (`@load_subgroup`
+ positional + `invoke_without_command` + `cmds/` discovery) is proven
by an integration test: click consumes the `nargs=1` positional as the
first token and resolves the *second* token as the subcommand, exactly
mirroring `wago`. Everything stays under `moat.db`; no `moat.rain`
top-level module. Subcommands (all site-scoped via `obj.site_name`):

```
# Site registry (wago-style verbs on the selected site):
moat db rain -                       # list all sites
moat db rain <SITE>                  # show one site   (no subcommand)
moat db rain <SITE> add              # create site
moat db rain <SITE> set              # modify site
moat db rain <SITE> delete           # delete site

# Per-entity CRUD, scoped to <SITE> (cmds/<entity>.py::cli groups):
moat db rain <SITE> controller  {show,add,set,delete}
moat db rain <SITE> valve       {show,add,set,delete}
moat db rain <SITE> feed        {show,add,set,delete}
moat db rain <SITE> sensor      {show,add,set,delete}   # --kind rain|temp|wind|sun
moat db rain <SITE> group       {show,add,set,delete}   # +/-days, +/-xdays, +/-valves
moat db rain <SITE> env         {show,add,set,delete}    # envgroup; sub: item {…}
moat db rain <SITE> day         {show,add,set,delete}    # day; sub: time {…}; range {…} (+/-days)
moat db rain <SITE> override    {group {…}, valve {…}, adjust {…}}
moat db rain <SITE> schedule    {show,add,set,delete,list}  # list ≈ old listschedule
moat db rain <SITE> history     {level {…}, hist {…}, log {…}}

# Engine / daemon (§7); site-scoped, in cmds/{gen,recalc,monitor}.py:
moat db rain <SITE> gen          # one-shot schedule generation  (old genschedule)
moat db rain <SITE> recalc       # one-shot level recalculation (old recalculate)
moat db rain <SITE> monitor      # long-running daemon           (old runschedule)
```

Inside each per-entity group, `show` lists all rows (scoped to
`obj.site_name`) when no `--name` is given, else dumps one record via
`yprint(obj.dump())` — exactly the box/thing pattern. Multi-value
options (`--valve`, `--day`, …) use `multiple=True` with `-NAME` meaning
"remove" (cf. `moat box typ --in -NAME`).

Each line above maps to `cmds/<name>.py::cli`; the thin `_main.py` group
owns no per-entity logic, so adding an entity is just a new `cmds/`
file. The command is `moat db rain …` (not `moat rain …`), and no
`moat.rain` top-level package is created.

### 6.4 Edits to existing files

1. `moat/db/_cfg.yaml` — append `moat.db.rain.model` and
   `moat.db.rain.model_` to the `schemas:` list.
2. Root `pyproject.toml` — add `"moat/db/rain/"` to `[tool.ty.src] include`.
3. `docs/moat-db/index.md` — add `../moat-db-rain/index` to the toctree.
4. `docs/index.md` — add a "DB: Irrigation" entry in the "Parts included"
   section (synopsis include from the packaging README).

No change to `moat/db/alembic/env.py` — the shared env already picks up
`Base.metadata` via `alembic_cfg`.

---

## 7. Scheduler engine

The engine is pure compute + IO layered over the ORM; it lives in
`moat/db/rain/{range.py,engine.py,monitor.py}` and is exercised by the
`gen`/`recalc`/`monitor` CLI verbs. It is ported from the legacy
`rainman/utils.py` + model `_range()` methods + management commands, with
the obsolete stack (qbroker/gevent/rpyc/Django ORM) replaced by
(anyio + SQLAlchemy + moat.link).

### 7.1 Interval algebra — `range.py`

Port `rainman/utils.py` near-verbatim: `range_coalesce`, `range_union`,
`range_intersection`, `range_invert`, `StoredIter`, and the `RangeMixin`
helpers (`range()`/`list_range()`). Drop `six` and the
request/threading middleware (dead Django plumbing). Keep the
generator-based `(start, length)` tuple protocol and the
`__main__` self-test (it becomes `tests/moat_db_rain/test_range.py`).
This module has **no ORM dependency** — pure iterators over datetimes.

### 7.2 Per-entity `_range()` ports — `engine.py`

Each legacy model method that yields permitted-watering intervals is
rewritten as a function taking a session + the entity + `(start, end)`:

- `controller_range(sess, controller, start, end, add=…)` — limits by
  `max_on` concurrent valves (heap of stop-times over `Schedule`).
- `feed_range(sess, feed, start, end, plusflow, add=…)` — limits by feed
  flow capacity (heap of `(stop, dflow)` over `Schedule`).
- `valve_range(sess, valve, start, end, forced=False, add=…)` — the
  orchestrator: intersects group-day ranges, group/xgroup exclusions,
  group overrides (allowed/not-blocked), valve overrides (forced/off),
  already-scheduled times, controller capacity, and feed capacity.
- `group_range`, `group_allowed_range`, `group_not_blocked_range`,
  `group_days_range`, `group_no_xdays_range`.
- `day_range` / `daytime_range` / `dayrange_range` — `DayTime._range`
  parses `descr` (§7.4); `DayRange` is the intersection of its `Day`s;
  `Day` is the union of its `DayTime`s.

All Django `Model.objects.filter(...)` become SQLAlchemy
`sess.execute(select(...).where(...))`. The heapq-driven concurrency
algorithms port unchanged.

### 7.3 Generation & recalculation — `engine.py`

- `generate_schedule(sess, *, site=None, controller=None, valve=None,
  horizon=…)` (old `genschedule`): for each valve, walk
  `valve_range(...)` over the horizon, pick slots until the valve's level
  rises from `stop_level`→`start_level` (watering time =
  `(start_level−stop_level)*area/flow`, adjusted by group `adj` and
  `EnvGroup` factor), honour `max_run`/`min_delay`, and insert `Schedule`
  rows (`seen=changed=forced=False`). Skip valves whose `Feed.disabled`.
- `recalculate(sess, *, site=None, valve=None, age=…)` (old
  `recalculate`): replay `History` rows to rebuild `Level` rows:
  `Δlevel = −evap(rate·shade·env_factor·dt) + rain·runoff − delivered`;
  clamp at `max_level`; skip `Level.forced` rows. Evaporation uses the
  `EnvGroup.env_factor()` weighted-nearest-neighbour interpolation
  (ported from `env.py`).

Both are plain synchronous functions operating inside a caller-supplied
session; the CLI wraps them in `database(cfg)` + `begin()`.

### 7.4 `DayTime.descr` parser

Old code: `from moat.times import time_until, humandelta`. **Action:**
locate the modern MoaT equivalent of `moat.times.time_until` (a
human-time-expression parser producing the next matching datetime). If
the module still exists (possibly renamed under `moat.util` or
`moat.lib.*`), depend on it; if gone, port the parser into
`moat/db/rain/times.py` and cover it with `test_range.py`. `DayTime`
stores `descr` verbatim regardless; parsing is engine-only.

### 7.5 The `monitor` daemon — `monitor.py` + `moat db rain <site> monitor`

Ports `runschedule` (1416 lines) from qbroker/gevent/rpyc to
**anyio + moat.link**. Responsibilities, preserved:

- Subscribe to weather sensors (`rain_sensor` rows, filtered by `kind`)
  via moat.link; accumulate into `History` rows; deprecate stale sensor
  readings (`SENSOR_TIME=5 min`, `SENSOR_MAXTIME=1 h` constants).
- Track `Site.rain_delay`: suppress scheduling while rain is recent.
- Periodically (and on sensor/level change) call `generate_schedule()`
  for the site's valves; mark new/changed `Schedule` rows.
- Send pending schedules (`seen=False`) to each `Controller` via
  moat-link RPC (the controller's fixed link address); mark `seen=True`; honour
  `changed`/`forced` flags.
- Maintain per-valve `Level` rows (call `recalculate()` incrementally);
  set `Valve.priority` when a cycle didn't finish.
- Append `Log` rows for notable events (errors, rain start/stop,
  manual overrides).

Implementation notes:

- Single anyio task group; one long-running task per concern (sensors,
  scheduler, dispatcher) communicating via anyio memory channels —
  replacing the old gevent `Queue`/`Semaphore`/`AsyncResult`.
- Use `moat.lib.run.wrap_main` / `asyncscope` for structured lifecycle
  (same harness the test helpers use).
- sd_notify watchdog: the systemd unit is `Type=notify`,
  `WatchdogSec=10` (§9); ping via the existing moat notify helper.
- **Never busy-loop / never sleep-to-workaround** (AGENTS.md): all waits
  are event-driven (link subscriptions, channel receives, timers via
  `anyio.sleep`).
- `Ctrl-C`/cancel: catch `anyio.get_cancelled_exc_class()` and re-raise
  after flushing the session.

The daemon is the **last** phase (§10); `gen`/`recalc` ship first so the
engine is testable without hardware.

---

## 8. Alembic strategy

- Do **not** create a separate alembic tree. Reuse `moat/db/alembic/`.
- After `model.py`/`model_.py` compile and are registered via the
  `schemas:` list, run `moat db migrate rev "add rain"` to autogenerate a
  new revision whose `down_revision = "dd1007d00e262b5c"` (current head).
- Hand-check the generated revision for: correct `rain_*` table names,
  named FK constraints (`fk_…`), `ondelete="CASCADE"`, the `kind`
  column on `rain_sensor`, composite-PK association tables, and
  `UniqueConstraint`s for every former `unique_together`.
- Verify with `moat db migrate check` (must report no diffs) and a
  round-trip `moat db migrate to <rev>` / back.
- Provide a `downgrade()` that drops the `rain_*` tables in reverse
  dependency order.
- The engine adds **no further migrations** — it only reads/writes rows.

### Status (Phase 5, done)

- Revision **`9a3f1c7e4b2d`** (`down_revision = "dd1007d00e262b5c"`)
  creates all 22 `rain_*` tables plus 8 non-unique indexes on the
  timestamp/`start` columns. It was **hand-written** in the `0000.py`
  style (explicit `op.create_table` with named `fk_…` `ondelete="CASCADE"`
  foreign keys, unnamed primary/unique constraints, separate
  `op.create_index` calls) rather than autogenerated, because driving
  `moat db migrate rev` needs a live config store + a reachable DB.
- `PathType` columns are emitted as `VARCHAR(200)` (the `impl` of the
  `TypeDecorator`); the migration carries no Python-side `default=`
  values, only the `server_default`s the model declares.
- **Validation:** `tests/moat_db_rain/test_migration.py` stamps an empty
  SQLite DB at `dd1007d00e262b5c`, upgrades to `9a3f1c7e4b2d`, reflects
  the result, and compares every `rain_*` table against
  `Base.metadata` (column names/types/nullability, primary key, foreign
  keys incl. `ondelete`, unique constraints, indexes), then downgrades
  and asserts all `rain_*` tables are gone.
- **SQLite caveat:** the *earlier* box/thing/label revisions use
  `op.create_foreign_key` (an `ALTER`), which SQLite rejects outside
  batch mode, so `command.upgrade(head)` cannot run the full chain on
  SQLite. The test therefore stamps past them and exercises only the
  rain revision (which is pure `create_table`/`create_index`/`drop` and
  SQLite-safe). `moat db migrate check` against a real MariaDB DB
  remains the production drift gate.

---

## 9. Debian packaging

Model the `debian/` dir on `packaging/moat-kv-akumuli/debian/` (a daemon
package with a systemd unit) and the template at
`moat/src/_templates/packaging/debian/`.

Files under `packaging/moat-db-rain/debian/`:

- **`control`** —
  `Source:` / `Package: moat-db-rain`, `Architecture: all`,
  `Maintainer: Matthias Urlichs <matthias@urlichs.de>`,
  `Build-Depends: dh-python, python3-all, debhelper (>= 13),
  debhelper-compat (= 13), python3-setuptools, python3-wheel`,
  `Depends: ${misc:Depends}, ${python3:Depends}, moat-db (>= 0.2.7),
  moat-link (>= 0.2), python3-anyio (>= 4.2), python3-asyncclick`,
  `Description:` two-line summary.
- **`rules`** —
  `export PYBUILD_NAME=moat-db-rain`; `dh $@ --with python3
  --buildsystem=pybuild`; an `override_dh_auto_install` that copies
  `moat-db-rain@.service` into `debian/` (cf. akumuli `rules`).
- **`changelog`** — seed `moat-db-rain (0.0.1-1) unstable; urgency=medium
  * Initial creation.` (version aligned with `pyproject.toml`).
- **`source/format`** — `3.0 (quilt)`.
- **`py3dist-overrides`** — map the Python distribution names of deps to
  Debian package names where they differ (e.g. `moat_lib_run
  python3-moat-lib-run`, `moat_lib_config python3-moat-lib-config`,
  `moat_db python3-moat-db`, `moat_link python3-moat-link`).
- **`moat-db-rain@.service`** — systemd template (instanced per site):
  ```
  [Unit]
  Description=MoaT irrigation monitor for %i
  After=moat-link.service
  ConditionFileNotEmpty=/etc/moat/moat.yaml

  [Install]
  WantedBy=multi-user.target

  [Service]
  Type=notify
  ExecStart=/usr/bin/moat db rain %i monitor
  EnvironmentFile=/usr/lib/moat/link/env
  EnvironmentFile=-/etc/moat/rain.env
  TimeoutSec=300
  WatchdogSec=10
  Restart=always
  RestartSec=30
  ```
  (mirrors `moat-kv-akumuli@.service`, with `ExecStart=/usr/bin/moat db
  rain %i monitor`).
- **No `.install` file** — `dh_installsystemd` auto-discovers and ships the
  `.service` (copied into `debian/` by `rules`) to `/lib/systemd/system/`,
  cf. `moat-kv-akumuli` (which has no `.install`).
- **`.gitignore`** — ignore built artifacts: `/files`, `/*.log`,
  `/*.debhelper`, `/*.debhelper-build-stamp`, `/*.substvars`,
  `/debhelper-build-stamp`, `/moat-db-rain`, `/moat-db-rain@.service`.

**Caveat / dependency gap:** the existing `moat-db`, `moat-db-box`,
`moat-db-label`, `moat-db-thing` packages have **no** `debian/` dir yet,
so `moat-db-rain`'s Debian `Depends: moat-db` cannot resolve until
`moat-db` is itself packaged. File a beads chore to add `debian/` to
`moat-db` (and ideally the other db sub-packages); until then the wheel
install path is the primary delivery, and the `moat-db-rain` `.deb` will
sit unbuilt-or-local. (Out of scope for this refactor to package moat-db;
just flagged.)

Versioning: start `moat-db-rain` at `0.0.1`; allocate via
`./mt src tag -s moat.db.rain -m` for minors.

---

## 10. Implementation phases

Each phase is a separate commit (pre-commit runs `ty` + tests).

1. **Scaffold.** Create `moat/db/rain/{__init__.py,model.py,model_.py,
   range.py,engine.py,monitor.py,_main.py}` + `moat/db/rain/cmds/
   {__init__.py,<one-stub>.py}` (stubs), `packaging/moat-db-rain/
   {pyproject.toml,README.md,LICENSE.txt,debian/…}`, `docs/moat-db-rain/
   {index.md,api.rst,MIGRATION.md}`, `tests/moat_db_rain/`. The thin
   `_main.py::cli` uses `@load_subgroup(sub_pre="moat.db.rain.cmds",
   sub_post="cli", ext_pre="moat.db.rain", ext_post="_main.cli",
   invoke_without_command=True)` + `@click.argument("site")` (the wago
   "site-before-verb" pattern), opens `database(cfg)`+`begin()`, and sets
   `obj.session`+`obj.site_name`. Wire `CfgStore.with_` in
   `__init__.py` (no `cli` export — discovery is via `ext_pre` →
   `_main.cli`, cf. box/label/thing), append to `moat/db/_cfg.yaml`
   schemas, add ty include, hook docs toctrees. Smoke-test all three
   layers: `moat db --help` lists `rain`; `moat db rain --help` lists
   the stub subcommand from `cmds/`; `moat db rain <stub-site>
   <stub-sub> --help` routes to the subcommand (proving the
   positional-then-subcommand disambiguation).
2. **Models — pass 1 (leaves).** `model.py` for entities with no in-rain
   FK dependents: `Site`, `Day`, `DayTime`, `EnvGroup`, `EnvItem`,
   `Sensor`, `Feed`. Define columns + self-contained relationships +
   `__tablename__`.
3. **Models — pass 2 (branches).** `Controller`, `Valve`, `Group`,
   `DayRange`, overrides, `GroupAdjust`, `Schedule`, `Level`, `History`,
   `Log`, and the four association `Table`s.
4. **`apply()` methods** (real overrides in `model.py`, §4.10): name-based
   FK resolution with the site as scope anchor, `Valve` passed as an
   object (compound key), Path fields as dotted strings, sentinel
   handling for M2M add/remove, duration-property wiring. `model_.py`
   stays a stub. *(Batch 1 done: Site/EnvGroup/Feed/Controller/Sensor/
   History/Valve + 26 tests, 98% coverage.)*
5. **Alembic revision.** Generate, hand-fix, verify (§8). *(Done: revision
   `9a3f1c7e4b2d`, hand-written, round-trip test in `test_migration.py`,
   39 rain tests / 99% coverage.)*
6. **CLI — CRUD.** Implement one `cmds/<entity>.py` at a time
   (site → controller → valve → feed → sensor → group → env → day →
   override → schedule → history), each exporting a `cli` group with
   show/add/set/delete. The thin `_main.py` needs no per-entity edits.
   *(In progress: site `add`/`set`/`delete` + `-` list / no-subcommand
   show in `_main.py`, and `controller` {show,add,set,delete} done.
   `cmds/_util.py` holds the shared scaffolding — `site_of`, `get_one`,
   `absent`, `require_name`, `list_in_site`, `is_given`, `site_opts` —
   so each entity file is little more than its options + four thin
   commands. End-to-end tests in `test_cli.py` drive the full `moat` CLI
   via `moat.src.test.run` with `-s moat.db.url` pointed at a temp
   SQLite DB; 44 rain tests / 99% coverage.)*

   Side fix: `moat.db.util.database()` had `except click.Exception:`
   (asyncclick exposes no `Exception` attr — it suggests `exceptions`),
   which turned every `UsageError` raised inside a DB command into an
   `AttributeError`. Corrected to `except click.exceptions.ClickException:`
   so click's user-facing errors pass through undecorated, as intended.
   This was latent — box/thing have no CLI tests raising through
   `database()`; rain's `controller add` (missing `--location`) is the
   first to exercise it.
7. **Engine — algebra.** Port `range.py` (§7.1) + `test_range.py` parity
   with the old `utils.py` self-tests.
8. **Engine — `_range()` ports + generation/recalc.** `engine.py`
   (§7.2–7.3); locate/port `time_until` (§7.4). `test_engine.py` seeds a
   temp sqlite DB and asserts generated schedules / recalculated levels.
   Expose via `cmds/gen.py` (`moat db rain <SITE> gen`) and
   `cmds/recalc.py` (`moat db rain <SITE> recalc`).
9. **Monitor daemon.** `monitor.py` (§7.5) on anyio + moat.link; wire
   `cmds/monitor.py` → `moat db rain <SITE> monitor`. `test_monitor.py`
   with a stubbed moat-link (no hardware). Add the systemd unit + Debian
   `rules` service-copy (§9).
10. **Polish.** Fill `README.md` synopsis/main and `index.md`; ensure
    `ty check --output-format github` is clean; confirm files in
    `tool.ty.src.include`; build wheel (`./mt src build`) and a local
    `.deb` to validate packaging.

---

## 11. Deferred work → beads issues

File these as separate issues (do **not** implement in this refactor):

- **Auth/access control** — design a MoaT-native replacement for
  `UserForSite` (cross-cutting, not rain-specific).
- **Data import** — one-shot script to migrate a live `rainman_*`
  SQLite/MySQL DB into `rain_*` tables (handle the dropped Site
  connection fields and the 4→1 sensor consolidation).
- **Config-driven schema registration** — move the `schemas:` list out
  of the central `moat/db/_cfg.yaml` into per-submodule `_cfg.yaml`s so
  `moat-db` no longer references optional subpackages (§4.9).
- **`genconfig` / `genhabconfig`** — port the controller-snippet and
  openHAB-config generators once the engine + monitor are stable.
- **Package `moat-db` (and friends) for Debian** — prerequisite for a
  installable `moat-db-rain` `.deb` (§9 caveat).

---

## 12. Resolved decisions & remaining implementation questions

### Resolved (ACKed)

1. **Site connection fields** — dropped (§4.2).
2. **Sensor consolidation** — one `rain_sensor` table with `kind` (§4.4).
3. **Schema registration** — central-list append (§4.9).
4. **Duration storage** — integer seconds + `timedelta` property (§4.3).
5. **Table prefix** — `rain_*` (§4.1).

### To confirm during implementation (not blocking the plan)

- **`moat db rain` registration (two-layer, confirmed by inspection +
  smoke test)**: (1) `moat db` is a `Loader(prefix="moat.db")` (so
  `ext_pre="moat.db"`, `ext_post="_main.cli"`) whose `list_commands`
  resolves `moat.db.<name>._main.cli` — rain is found as
  `moat.db.rain._main.cli`, like `box`/`thing`/`label`; `__init__.py`
  must **not** export `cli` (else `moat db --help` lists `rain` twice).
  (2) `moat db rain`'s own group uses
  `@load_subgroup(sub_pre="moat.db.rain.cmds", sub_post="cli", …)`, so
  its `list_commands` resolves `moat.db.rain.cmds.<name>.cli` — each
  `cmds/<entity>.py` exports `cli`. No `moat.rain` top-level module is
  created. (3) The group takes a positional `<SITE>` before the verb
  (`moat db rain <SITE> <verb>`, the `mt link wago NAME <verb>` pattern):
  `invoke_without_command=True` + `@click.argument("site")`; click
  consumes the `nargs=1` positional as the first token and resolves the
  second as the subcommand — proven by an integration test combining
  `@load_subgroup` + positional + `invoke_without_command` + `cmds/`
  discovery. Implemented in the Phase-1 scaffold, not deferred.
- **`moat.times.time_until` successor**: locate the modern MoaT module
  providing human-time-expression parsing for `DayTime.descr`; port if
  absent (§7.4).
- **moat-link client API surface** for the monitor (subscribe to sensor
  vars, RPC to controllers): pin to the current `moat.link` API in
  Phase 9.
