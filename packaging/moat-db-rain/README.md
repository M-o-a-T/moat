# MoaT-DB-Rain

% start synopsis
% start main

This package provides irrigation scheduling and monitoring for MoaT,
migrated from the legacy Django `rainman` app to a `moat.db.rain`
SQLAlchemy + Alembic submodule. It supersedes the old `rainman` Django
app with command-line CRUD for every irrigation entity, a scheduler
engine that computes when each valve may run, and a per-site
`moat db rain <SITE> monitor` daemon that drives the live system. The
schema lives in a shared database alongside `moat.db.box`,
`moat.db.thing`, and `moat.db.label`, with all tables prefixed `rain_`
to avoid collisions.

% end synopsis

## Installation

Install the Debian package, which pulls in `moat-db`, `moat-link`, and
`python3-anyio`:

```console
# dpkg -i moat-db-rain_0.0.1-1_all.deb
# apt-get install -f   # resolve any missing dependencies
```

Alternatively, install the wheel with pip into the same environment as
the rest of MoaT:

```console
$ pip install moat-db-rain
```

Before the daemon can run, the shared database must hold the rain
schema. Apply the Alembic migration from the `moat-db` package:

```console
# moat db migrate update
```

The full schema and design history — the legacy `rainman` analysis, the
locked design decisions, and the phased implementation record — live in
the `moat-db-rain` documentation (*MIGRATION.md*).

## Command-line interface

All operations are reached as `moat db rain <SITE> <verb>`, mirroring
the `moat link wago NAME <verb>` pattern. The site is named before the
verb; `moat db rain -` lists all sites and `moat db rain <SITE>` (no
subcommand) shows one site.

```
moat db rain <SITE>                         # show one site
moat db rain <SITE> add                     # create a site
moat db rain <SITE> controller {show,add,…} # manage controllers
moat db rain <SITE> valve {show,add,…}      # manage valves
moat db rain <SITE> feed {show,add,…}       # manage water feeds
moat db rain <SITE> sensor {show,add,…}     # manage weather sensors
moat db rain <SITE> group {show,add,…}      # manage valve groups
moat db rain <SITE> env {show,add,…}        # manage env groups
moat db rain <SITE> day {show,add,…}        # manage day definitions
moat db rain <SITE> dayrange {show,add,…}   # manage day ranges
moat db rain <SITE> override {…}            # manage overrides
moat db rain <SITE> schedule {…}            # manage schedules
moat db rain <SITE> history {…}             # weather history + logs
moat db rain <SITE> gen                      # generate schedules
moat db rain <SITE> recalc                   # recalculate levels
moat db rain <SITE> monitor                  # run the daemon
```

The `gen` and `recalc` verbs expose the scheduler engine as one-shot
commands, so the engine can be exercised without running the daemon.

## Service

The `monitor` command runs a long-running anyio daemon that subscribes
to weather sensors via moat.link, periodically calls the scheduler
engine, dispatches pending valve commands to controllers, and maintains
level / history / log rows. It is designed to run as a `Type=notify`
systemd service.

The package ships a **templated** unit, `moat-db-rain@.service`, so one
instance is started per irrigation site. Enable and start the daemon for
a site by substituting the site name for the instance specifier:

```console
# systemctl enable --now moat-db-rain@<site>.service
```

List the running instances with `systemctl list-units 'moat-db-rain@*'`,
and follow one with `journalctl -u moat-db-rain@<site> -f`. The unit
starts after `moat-link.service`, pings the systemd watchdog every ten
seconds (`WatchdogSec=10`), and restarts on failure.

## Configuration

The daemon reads MoaT's central config at `/etc/moat/moat.yaml`; the
unit refuses to start unless that file is non-empty
(`ConditionFileNotEmpty`). Database and moat.link connection settings
live there, not in per-row site columns — see the `moat-db` and
`moat-link` packages for the relevant keys.

Per-site irrigation parameters (evaporation rate, rain delay, valve
levels, feed flow limits, schedules, and so on) are stored in the
database and managed with the `moat db rain <SITE> …` commands above,
not in flat config files. An optional `/etc/moat/rain.env` file, sourced
by the unit via `EnvironmentFile`, may override environment variables for
all instances.

% end main
