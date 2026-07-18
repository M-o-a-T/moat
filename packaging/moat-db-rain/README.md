# MoaT-DB-Rain

% start synopsis
% start main

This module provides irrigation scheduling and monitoring for MoaT,
migrated from the legacy Django `rainman` app to a `moat.db.rain`
SQLAlchemy + Alembic submodule. It supersedes the old `rainman` Django
app with command-line CRUD, a scheduler engine, and a per-site
`moat db rain <SITE> monitor` daemon.

## Overview

The rain module manages every persistent entity of an irrigation
system: sites, controllers, valves, feeds, weather sensors, groups,
environmental effects, day/time schedules, overrides, and the generated
watering schedule. The schema lives in a shared database alongside
`moat.db.box`, `moat.db.thing`, and `moat.db.label`, with all tables
prefixed `rain_` to avoid collisions.

### Command-line interface

All operations are reached as `moat db rain <SITE> <verb>`, mirroring
the `moat link wago NAME <verb>` pattern. The site is named before the
verb; `moat db rain -` lists all sites.

```
moat db rain <SITE>                         # show one site
moat db rain <SITE> add                     # create a site
moat db rain <SITE> controller {show,add,…} # manage controllers
moat db rain <SITE> valve {show,add,…}      # manage valves
moat db rain <SITE> feed {show,add,…}       # manage water feeds
moat db rain <SITE> sensor {show,add,…}     # manage weather sensors
moat db rain <SITE> group {show,add,…}      # manage valve groups
moat db rain <SITE> env {show,add,…}        # manage env groups
moat db rain <SITE> day {show,add,…}         # manage day definitions
moat db rain <SITE> dayrange {show,add,…}   # manage day ranges
moat db rain <SITE> override {…}             # manage overrides
moat db rain <SITE> schedule {…}             # manage schedules
moat db rain <SITE> history {…}             # weather history + logs
moat db rain <SITE> gen                      # generate schedules
moat db rain <SITE> recalc                   # recalculate levels
moat db rain <SITE> monitor                  # run the daemon
```

### Scheduler engine

The engine (`moat.db.rain.engine`) ports the legacy `rainman`
interval-algebra and schedule-generation logic to SQLAlchemy. It
computes when each valve may run by intersecting group-day ranges,
overrides, controller capacity, and feed capacity, then plans watering
slots until each valve's level deficit is met. The `gen` and `recalc`
commands expose this as one-shot CLI verbs.

### Monitor daemon

The `monitor` command runs a long-running anyio daemon that subscribes
to weather sensors via moat.link, periodically calls the scheduler
engine, dispatches pending valve commands to controllers, and maintains
level / history / log rows. It is designed to run as a `Type=notify`
systemd service (template unit `moat-db-rain@<SITE>.service`).

% end synopsis
% end main
