# Architecture — moat.db

Conventional **relational-database layer** (SQLAlchemy 2.0 + Alembic) for
structured/tabular application data. **Unrelated to `moat.kv`** — they share
only the `moat.*` namespace and the `moat.lib.config` registration
convention. KV is a bespoke distributed tree; DB is a classic ORM+migration
stack over a SQL engine.

## Files

- `schema.py` — `Base(DeclarativeBase)` (SQLAlchemy 2.0 declarative). Auto
  `__tablename__` (lowercased class name) + surrogate integer PK `id`. Adds
  `dump()`/`apply()` helpers.
- `util.py` — `load(cfg)` imports configured schema modules, builds an
  `Engine` via `create_engine(cfg.url)`, configures a global `sessionmaker`
  `Session`, sets SQLite `PRAGMA foreign_keys=ON`. `database(cfg)` is a
  `@contextmanager` yielding a `Mgr` (thin wrapper exposing
  `.one(table, **kw)`); the active session is stashed in a `ContextVar`
  `session`. `alembic_cfg(gcfg, sess)` builds an in-memory alembic
  `Config` pointing at `moat/db/alembic/`.
- `_main.py` — Click CLI (`cli` group via `load_subgroup`): `init`, `get`,
  and a `migrate` subgroup — `update` (`alembic upgrade head`), `rev`
  (autogenerate), `check`, `to <rev>` (upgrade+downgrade), `history`, `show`.
  Comment at top: *"The main code must not load any sqlalchemy code. sqlalchemy
  might not be present."* — SQLAlchemy is lazily imported.
- `model.py` — placeholder (`"nothing yet"`).
- `alembic/` — standard Alembic scaffolding: `env.py` (online/offline
  `run_migrations_*` pulling `metadata`/`connection` from
  `config.attributes`), `versions/` for revision scripts, `script.py.mako`.
- `_cfg.yaml` — `schemas:` list (registers app schema modules + `*_`
  underscore companions to break import cycles); default
  `url: sqlite:////nonexistent/test.db`.

## Application schemas

Subpackages, each registering via the `schemas:` list in `_cfg.yaml`:
- `db/label` — labeling.
- `db/box` (`box/model.py`: `BoxTyp`, `boxtyp_tree` adjacency table) — box
  types/taxonomy.
- `db/thing` — generic things.
- `db/rain` (`rain/model.py` ~1043 lines of SQLAlchemy declarations;
  `rain/engine.py` ~34 KB business logic) — irrigation/rain records.
- `db/inv` — inventory.

## Entry points

- CLI: `moat db {init,get,migrate {update,rev,check,to,history,show}}`
  (`db/_main.py`).
- Library: `moat.db.load(cfg)`, `moat.db.database(cfg)` (re-exported from
  `db/__init__.py`, which also calls `moat.lib.config.register`).
- Migrations: `alembic` via `alembic_cfg()`; revision scripts in
  `db/alembic/versions/`.
