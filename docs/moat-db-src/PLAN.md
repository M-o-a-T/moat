# Plan: `moat db src` — source-package archive tracking

Track, in the `moat.db` relational store, a catalogue of **source packages**
(SPKGs) and, per package, its **archives** (named remote/local copies with a
URL and a role), the controlled vocabularies for **archive roles** and
**branch roles**, and a table of **local branches** with free-text status.

This persists information that `moat.src` currently derives from config +
live git/forge queries. The store is primarily a *manual catalogue*, but it
also supports a **round trip to a local git repo**: `import` reads an
existing on-disk repo into the DB record, `export` materialises a repo
from the DB record. Crucially, **this is not the `moat.src` forge-move
machinery** — there are no tokens, no remote-repo creation, no branch/tag
deletion, no README rewriting. Import/export talk straight to a local git
working tree via `git` plumbing (subprocess) and to the DB.

Conventions follow the existing `moat.db` domains (`box`, `thing`, `label`,
`rain`). Reference impls: `moat/db/box/` (cleanest), `moat/db/thing/`,
`moat/db/rain/` (positional-then-verb CLI; `rain_*` table prefix; `Text`;
timestamps).

> **Precondition:** implement on a branch carrying the full tree (e.g. a
> topic branch off `main`). The current `closed` checkout is stripped to
> `README.md`; `moat/db/**.py` are absent on disk here.

---

## 1. Vocabulary & naming decisions

| Concept (user’s words)             | Model class   | Table              | CLI location                          | Scope     |
|------------------------------------|---------------|--------------------|----------------------------------------|-----------|
| named source package (SPKG)         | `Spkg`        | `src_spkg`         | `add SPKG` / `at SPKG …`               | anchor    |
| known archive (name+URL+role)        | `Archive`     | `src_archive`      | `at SPKG remote NAME …`                | per-SPKG  |
| table of known archive roles        | `ArchiveRole` | `src_archive_role` | `archive NAME …`                        | global    |
| table of known branch roles         | `BranchRole`  | `src_branch_role`  | `branch NAME …`                        | global    |
| local branch + status               | `LocalBranch` | `src_branch`       | `at SPKG branch NAME …`                | per-SPKG  |

Key choices:

- **Tables prefixed `src_`** (à la `rain_*`) to stay tidy in the shared
  `Base.metadata`. `Base` auto-lowercases class names, so override
  `__tablename__` on every class.
- **Instance model is `Archive`** (matches “known archives” in the
  request); it is exposed via the **`remote`** verb because from a
  package’s POV these are its remotes/locations. `Archive.archiverole`
  ⇒ `ArchiveRole`. The role table is exposed via **`archive`** (global).
- **`at SPKG` scopes per-package work.** Global registries (`archive`,
  `branch`) sit beside `at` on the top group; per-SPKG verbs (`remote`,
  `branch`, `set`, `delete`, `list`) sit under `at SPKG`. Thus `branch`
  at top level = `BranchRole` registry; `branch` under `at SPKG` =
  `LocalBranch` of that package. Different groups ⇒ different namespaces
  ⇒ no click name clash and no union-of-options.
- **No optional positionals, no `-n`/`--pkg`.** Every positional is
  required wherever it appears. Enumeration is always the explicit
  `list` verb (never “omit the name”). Entity `NAME`s are required
  positionals on `show`/`add`/`set`/`delete`.
- **Seeds live in `moat/db/src/_seed.yml`**, applied by a dedicated Alembic
  *data* migration. Nothing seed-related goes in `_cfg.yaml` / `CfgStore`.

---

## 2. Command-line reference

Top group opens the DB session (mirrors `box`/`rain`):

```
moat db src [<verb>] ...
```

`cli` callback: `ctx.with_resource(database(obj.cfg.db))` +
`sess.begin()`; set `obj.session`. Decorate
`@load_subgroup(prefix="moat.db.src", invoke_without_command=True)`.
With no subcommand, behave as global `list`.

### 2a. Global (top level)

```
moat db src                                     # ≡ list
moat db src list                                # list all SPKGs
moat db src add SPKG [--comment …]              # create a SPKG
```

`archive` and `branch` are **groups** (the global role registries), each
with `list` plus `show`/`add`/`set`/`delete NAME`:

```
moat db src archive list
moat db src archive add    NAME [--comment …] [--rank N]
moat db src archive show   NAME
moat db src archive set    NAME [--comment …] [--rank N]
moat db src archive delete NAME

moat db src branch list
moat db src branch add    NAME [--comment …] [--abstract] [--real]
moat db src branch show   NAME
moat db src branch set    NAME [--comment …] [--abstract] [--real]
moat db src branch delete NAME
```

### 2b. Per-SPKG (scoped via `at SPKG`)

`at` is a group taking a required `SPKG` positional. Its callback verifies
the SPKG exists (`sess.one(Spkg, name=SPKG)`, else error pointing at
`moat db src add SPKG`) and stashes it on `obj.spkg`.

```
moat db src at SPKG                             # ≡ list (SPKG detail)
moat db src at SPKG list                        # show SPKG detail
moat db src at SPKG set    [--comment …]        # modify the SPKG
moat db src at SPKG delete                      # remove SPKG (cascades)

moat db src at SPKG remote list
moat db src at SPKG remote add    NAME --role R --url U [--ext-url …] [--api …] [--default] [--comment …]
moat db src at SPKG remote show   NAME
moat db src at SPKG remote set    NAME [--role R] [--url U] [--ext-url …] [--api …] [--default|--no-default] [--comment …]
moat db src at SPKG remote delete NAME

moat db src at SPKG branch list
moat db src at SPKG branch add    NAME [--role R] [--status …] [--commit SHA]
moat db src at SPKG branch show   NAME
moat db src at SPKG branch set    NAME [--role R] [--status …] [--commit SHA]
moat db src at SPKG branch delete NAME
```

### 2c. Concrete examples

```bash
# ---- global registries ----
moat db src                                      # list SPKGs
moat db src archive list
moat db src archive add upstream --comment "Public origin" --rank 1
moat db src archive set upstream --rank 2
moat db src archive show upstream
moat db src archive delete upstream
moat db src branch list
moat db src branch add main                       # BranchRole
moat db src branch add feature --abstract --comment "Short-lived"
moat db src branch set feature --real
moat db src branch show main
moat db src branch delete main

# ---- packages ----
moat db src add moat-util --comment "Utility lib"
moat db src at moat-util                         # show detail
moat db src at moat-util set --comment "Utility library (core)"
moat db src at moat-util delete

# ---- remotes (Archive) of a package ----
moat db src at moat-util remote list
moat db src at moat-util remote add github \
    --role upstream --url https://github.com/m-o-a-t/moat-util.git \
    --ext-url https://github.com/m-o-a-t/moat-util --api github --default
moat db src at moat-util remote set codeberg --role mirror
moat db src at moat-util remote show github
moat db src at moat-util remote delete github

# ---- local branches (LocalBranch) of a package ----
moat db src at moat-util branch list
moat db src at moat-util branch add main --role main --status "tracking upstream"
moat db src at moat-util branch set devel --status @/tmp/status.txt   # long text from file
moat db src at moat-util branch set bug42 --status -                  # clear status
moat db src at moat-util branch set bug42 --commit 0123abcd
moat db src at moat-util branch show devel
moat db src at moat-util branch delete devel

# ---- import / export (local-git round trip) ----
# Bootstrap a brand-new SPKG record from an existing repo (SPKG must not exist):
moat db src import ~/src/moat-util --name moat-util --comment "Utility lib"
#   infers SPKG name from the repo basename if --name omitted

# Re-sync an existing SPKG from its checked-out repo (updates remotes/branches,
# preserves DB-only `status` text, fails if SPKG missing):
moat db src at moat-util import ~/src/moat-util
#   path defaults to the current directory when omitted

# Materialise a repo from the DB record (clones the default archive, then
# wires up the other remotes; refuses a non-empty/non-clean dest):
moat db src at moat-util export --dest ~/scratch/moat-util

# Pin a local naming convention once, in ~/.gitconfig, instead of repeating --role:
#   [moat.src.roles]
#       origin = upstream
#       upstream = upstream
#       gh-personal = fork
moat db src import ~/src/foo --name foo          # picks roles up automatically
```

### 2d. Option sets per leaf

Declared with `option_ng(...)` / `click.option(...)` on each leaf. Only the
options relevant to that leaf’s single mode are declared — no unions.

- `archive` leaves (global): `--comment`, `--rank INT`.
- `branch` leaves, **global** (BranchRole): `--comment`, `--abstract`, `--real`.
- `branch` leaves, **under `at`** (LocalBranch): `--role <rolename>`,
  `--status <text|@file|->`, `--commit <sha>`.
- `remote` leaves (under `at`): `--role <rolename>`, `--url URL`,
  `--ext-url URL`, `--api <github|forgejo|radicle|localgit>`,
  `--default` / `--no-default`, `--comment`.
- `add` (top, SPKG create): `--comment`.
- `set` under `at` (SPKG modify): `--comment`.
- `import` (top, bootstrap SPKG): `PATH` positional (required), `--name SPKG`
  (optional; inferred from repo basename if omitted), `--comment`, repeatable
  `--role REMOTE=ROLE` overrides, `--mirror REMOTE` (mark a push-capable
  remote as `mirror` rather than `local`). Refuses if the SPKG already exists.
- `import` (under `at SPKG`, re-sync): optional `PATH` (defaults to `.`);
  `--role REMOTE=ROLE` repeats; `--mirror REMOTE` repeats. Refuses if the
  SPKG is missing — directs to `moat db src import PATH --name SPKG`.
- `export` (under `at SPKG`): `--dest PATH` (required), `--bare` (clone a
  bare repo). Refuses if `--dest` exists and is non-empty, or is a dirty
  git worktree.

`--status` parsing: a value beginning with `@` reads the rest as a file
(`@-` ⇒ stdin); a lone `-` ⇒ clear (`None`). Otherwise the literal string.

`--role REMOTE=ROLE` (import only): forces the role assigned to git remote
  `REMOTE` to be `ROLE` (an `ArchiveRole` name), bypassing inference. May
  repeat. Unknown `ROLE` ⇒ `UsageError` (role must exist in the registry).

Errors follow house style: `raise click.UsageError(...)` for bad args;
`print(msg, file=sys.stderr); sys.exit(1)` for duplicate/missing records
(matching `box`/`thing`).

---

## 3. Data model (`moat/db/src/model.py`)

All subclass `moat.db.schema.Base` (surrogate `id`, `dump()`, `apply()`).
Override `__tablename__` to add the `src_` prefix.

### `Spkg` — `src_spkg`
```
name    String(60)  UNIQUE NOT NULL   # dotted/dashed package name
comment String(200) NULL
prefix  String(20)  NULL              # for Beads issue tracker
```
Relationships (attached in `model_.py`): `archives: set[Archive]`,
`branches: set[LocalBranch]` (both cascade-delete).
`dump()`: name, comment, then `archives: [{role,name,url,default}]`,
`branches: [{name,role,status,updated,commit}]`.

### `ArchiveRole` — `src_archive_role`  (global registry)
```
name    String(40)  UNIQUE NOT NULL
comment String(200) NULL
rank    Integer      NULL              # display order, lower=earlier
```
Relationship: `archives: set[Archive]`.
`dump()`: name, comment, rank, count of archives using it.

### `BranchRole` — `src_branch_role`  (global registry)
```
name     String(40)  UNIQUE NOT NULL
comment  String(200) NULL
abstract Boolean NOT NULL DEFAULT 0   # True ⇒ not a long-lived role
```
Relationship: `branches: set[LocalBranch]`.
`dump()`: name, comment, abstract, count of branches using it.

### `Archive` — `src_archive`  (per-SPKG; the “remote”)
```
spkg_id   FK src_spkg.id  ON DELETE CASCADE
role_id   FK src_archive_role.id
name      String(40)                     # label: github/codeberg/local…
url       String(200) NOT NULL
ext_url   String(200) NULL               # human-facing web URL
api       String(40)  NULL               # github|forgejo|radicle|localgit
comment   String(200) NULL
default   Boolean NOT NULL DEFAULT 0     # ≤1 TRUE per spkg (enforced in code)
UNIQUE(spkg_id, name)
```
Relationships: `spkg: Spkg`, `archiverole: ArchiveRole`.
`dump()`: role, name, url, ext_url, api, default, comment.

### `LocalBranch` — `src_branch`  (per-SPKG)
```
spkg_id  FK src_spkg.id  ON DELETE CASCADE
role_id  FK src_branch_role.id  NULL
name     String(80)                     # branch name
status   Text  NULL                     # possibly-long free text
commit   String(64) NULL                # pinned sha (40/64 chars)
updated  DateTime NULL                  # stamped on status/commit change
UNIQUE(spkg_id, name)
```
Relationships: `spkg: Spkg`, `branchrole: BranchRole | None`.
`dump()`: name, role, status, updated, commit.

Cross-domain relationships: none expected ⇒ no `TYPE_CHECKING` stubs
needed beyond intra-`src` pairs (still resolved in `model_.py`).

---

## 4. `moat/db/src/model_.py` (cycle breaker + `apply()`)

Import concrete classes, attach `relationship(...)` with `back_populates`,
monkeypatch `apply` per the `box`/`thing` recipe. Use `moat.util.NotGiven`
sentinel; `None` means “clear”.

Pairs:
- `Spkg.archives ⇄ Archive.spkg` (collection_class=set)
- `Spkg.branches ⇄ LocalBranch.spkg` (collection_class=set)
- `ArchiveRole.archives ⇄ Archive.archiverole`
- `BranchRole.branches ⇄ LocalBranch.branchrole`

`apply` methods:

- **`spkg_apply(self, *, comment=NotGiven, **kw)`** → `Base.apply`.
- **`archiverole_apply(self, *, comment=NotGiven, rank=NotGiven, **kw)`**
  → `Base.apply`; set `rank` (None allowed to clear).
- **`branchrole_apply(self, *, comment=NotGiven, abstract=False, real=False, **kw)`**
  → like `thingtyp_apply`: `abstract`+`real` mutually exclusive; set the
  boolean.
- **`archive_apply(self, *, role=NotGiven, url=NotGiven, ext_url=NotGiven,
  api=NotGiven, default=NotGiven, comment=NotGiven, **kw)`**:
  - `Base.apply` for scalars.
  - `role`: required on create; immutable thereafter (reject rename, like
    `ThingTyp` on `Thing`). Resolve via `sess.one(ArchiveRole, name=role)`.
  - `url`: required on create.
  - `default`: if `True`, within `sess.no_autoflush` clear `default` on
    sibling `Archive` rows of the same `spkg` (single-default invariant,
    à la `ThingTyp` single-top rule). If `False`, just set False.
  - `api`: store as-is (free string; optionally validated against the four
    known names — recommend: warn, don’t hard-fail, to stay extensible).
- **`localbranch_apply(self, *, role=NotGiven, status=NotGiven,
  commit=NotGiven, **kw)`**:
  - `Base.apply` for scalars.
  - `role`: `NotGiven`⇒unchanged; `None`/`"-"`⇒clear; else resolve via
    `sess.one(BranchRole, name=role)` (nullable FK).
  - `status`: detect change; if changed (including clearing), stamp
    `self.updated = now()` (`moat.util.times.now`). Value pre-parsed by
    the CLI leaf (`@file`/`-`/literal) so `apply` gets a plain string/None.
  - `commit`: if changed, also stamp `updated`.

The `at SPKG` callback resolves and stashes the `Spkg` row; `remote`/`branch`
leaves construct `Archive(spkg=obj.spkg)` / `LocalBranch(spkg=obj.spkg)`
and call `apply(...)` without a `spkg=` argument.

Helpers: `sess = session.get()`; wrap relation work in `with sess.no_autoflush`.

---

## 4a. Git interplay: `import` / `export` (NOT `moat.src`)

Import and export bridge the DB record and a **local git working tree** via
plain `git` plumbing (subprocess). They deliberately do **not** use the
`moat.src.api.*` forge stack: no authentication, no remote-repo creation, no
branch/tag deletion, no README rewriting. Network access during `export` is
limited to cloning the default archive's URL (whatever the operator put
there); `import` touches no network at all.

### Shared helper: role resolution

Assigning an `ArchiveRole` to a discovered git remote follows a strict
three-tier precedence (highest wins):

1. **CLI override** — `--role REMOTE=ROLE` on the `import` command.
2. **Git config** — `moat.src.roles.<REMOTE>` in any reachable git config
   (repo-local, `~/.gitconfig`, system). Lets a user pin their personal
   naming convention once instead of repeating flags. Read via
   `git config --get moat.src.roles.<REMOTE>` (first match wins, matching
   git's scalar semantics).
3. **Heuristic** — based on the remote's configured fetch/push URLs:
   - remote name `origin` or `upstream` ⇒ role **`upstream`**;
   - otherwise, if the remote has **no `push` URL** (fetch-only) ⇒ role
     **`fork`** (you can pull but not push — typical of a fork you watch);
   - otherwise (push-capable): role **`mirror`** if `--mirror REMOTE` was
     passed for it, else role **`local`** (your own writable copy).

Resolved role must exist as an `ArchiveRole` row; if the heuristic yields a
role not in the registry, `import` aborts with a clear message directing to
`moat db src archive add <ROLE>`. Hence the seed list includes `fork` and
`local` (see §5).

Remote name → role mapping is computed once per import and reported in the
command's summary output (so the user sees what was inferred and can redo
with `--role`/`--mirror` or a git-config entry).

### `import` — repo → DB

Two entry points sharing one resolver:

- **Top-level `import PATH --name SPKG`** — bootstraps a **new** SPKG.
  Requires `PATH` to be a git repo; `--name` defaults to the repo's basename
  (sanitised). Creates the `Spkg` row, then discovers remotes/branches and
  populates `Archive`/`LocalBranch` rows. **Refuses if the SPKG already
  exists** (directs to `moat db src at SPKG import`).
- **`at SPKG import [PATH]`** — re-syncs an **existing** SPKG. `PATH`
  defaults to the current directory. **Refuses if the SPKG is missing**
  (directs to `moat db src import PATH --name SPKG`). Updates the
  `Archive`/`LocalBranch` rows to match the repo, preserving DB-only state
  (see “Preservation” below).

Discovery (via `git` plumbing, no network):

- **Remotes → `Archive`**: `git remote -v` grouped by name; each remote's
  fetch URL → `Archive.url`, push URL presence informs the heuristic;
  `Archive.name` = remote name; `Archive.api` guessed from URL scheme/host
  (`github.com`→`github`, `*.codeberg.org`→`forgejo`, `rad://` or radicle
  hints→`radicle`, else `localgit`) — guess only, overridable later via
  `remote set`. Exactly one `Archive` is marked `default`: the remote named
  `origin` if present, else the first remote alphabetically.
- **Branches → `LocalBranch`**: `git for-each-ref refs/heads/*` yields local
  branch names + tip SHAs → `LocalBranch.name` / `LocalBranch.commit`.
  `LocalBranch.role` is **left unset** on import (a branch's role is a
  human judgement, not derivable from git); set later via
  `at SPKG branch set NAME --role R`. `LocalBranch.status` is preserved /
  untouched (DB-only).
- **Default branch**: `git symbolic-ref HEAD` → noted in the SPKG detail
  dump (no dedicated column in this iteration; could annotate the matching
  `LocalBranch` via a future flag).

Upsert semantics (re-sync): match `Archive` by `(spkg, name)` and
`LocalBranch` by `(spkg, name)`. Existing rows are updated in place
(role via the resolver, url/ext_url/api refreshed, commit refreshed);
remotes/branches no longer present in the repo are **reported but not
deleted** (avoid surprising data loss) — `--prune` flag deletes them.

Preservation: `LocalBranch.status` and `LocalBranch.role` are never
overwritten by import. `Archive.comment` is preserved unless the remote's
URL changed (then reset, since the old comment likely no longer applies).

Idempotent: re-running `import` on an unchanged repo is a no-op (modulo
`updated` stamps, which only fire on actual `status`/`commit` changes).

### `export` — DB → repo

`at SPKG export --dest PATH [--bare]` materialises a repo from the DB record:

1. Resolves the SPKG's **default** `Archive` (the row with `default=True`;
  if none, refuses with a pointer to `remote set NAME --default`).
2. `git clone [--bare] <default.url> <PATH>` (network: only this URL).
3. For every **other** `Archive` row of the SPKG: `git remote add <name>
  <url>` (sets the remote's fetch URL to `Archive.url`; a push variant is
  not stored in this iteration, so no `set-url --push`).
4. For every `LocalBranch` row: ensure the branch exists locally —
  `git branch <name> origin/<name>` if it exists on the cloned default,
  else `git branch <name> <commit>` when `LocalBranch.commit` is set,
  else skip with a warning (can't conjure a branch with neither a ref nor
  a commit). Does **not** force-checkout any branch.
5. Writes nothing to the worktree for `status` (DB-only; see §11).

Safety: refuses if `--dest` exists and is non-empty, or is a git worktree
with uncommitted changes. `--force` overrides the emptiness check (still
refuses on a dirty worktree).

`export` is deterministic given the DB state: re-exporting the same SPKG to
a fresh path reproduces the same remote/branch topology. It is **not** the
inverse of `import` — `status`/`role`/comments are DB-side annotations
that don't round-trip through git.

---

## 5. Seeding — `moat/db/src/_seed.yml`

Human-editable source of truth for the default role vocabularies. Applied
by a dedicated Alembic **data** migration (§6). Format:

```yaml
# Default role vocabulary for moat.db.src.
# Applied by Alembic revision <hex>_seed_src_roles.
archive_role:
  - {name: upstream,  rank: 1, comment: "Primary public source (origin/upstream remote)"}
  - {name: fork,      rank: 2, comment: "Fetch-only remote you watch but can't push to"}
  - {name: mirror,    rank: 3, comment: "Push-capable mirror (--mirror on import)"}
  - {name: local,     rank: 4, comment: "Your own writable local copy (push-capable, not mirrored)"}
  - {name: internal,  rank: 5, comment: "Internally-hosted authoritative copy"}
  - {name: radicle,   rank: 7, comment: "Radicle peer-to-peer replica"}
  - {name: backup,    rank: 9, comment: "Offline / backup copy"}

branch_role:
  - {name: main,     comment: "Primary integration branch"}
  - {name: release,  comment: "Maintenance / release branch"}
  - {name: develop,  comment: "Long-lived development branch"}
  - {name: feature,  abstract: true, comment: "Short-lived feature work"}
  - {name: migrated, comment: "Marker branch left by moat.src move"}
```

Nothing from this file is loaded into `moat.db` runtime config. The
migration reads it at upgrade time and inserts the rows; downgrade deletes
exactly the seeded names (so user-added roles survive a rollback).

---

## 6. Migrations (`moat/db/alembic/versions/`)

Two new linear revisions, authored via `moat db migrate rev` then hand-edited:

1. **`<hex>_add_src_tracking.py`** (schema) — `down_revision` = current head.
   `op.create_table` for `src_spkg`, `src_archive_role`, `src_branch_role`,
   `src_archive`, `src_branch` with FKs, `UniqueConstraint`s, `server_default`s
   for booleans. Order: roles before `src_archive`/`src_branch`; `src_spkg`
   before its dependents. Mirror `0000.py`’s style (named FKs, comments).
2. **`<hex>_seed_src_roles.py`** (data) — `down_revision` = prev rev.
   Reads `moat/db/src/_seed.yml` via `yload`, inserts into
   `src_archive_role` / `src_branch_role` with `sa.insert(meta.tables[…])`.
   Missing file ⇒ no-op with a logged warning. Downgrade: `sa.delete(...)
   .where(name.in_(seeded_names))` per table.

Verify:
```bash
moat db migrate check     # no residual diffs
moat db migrate update     # apply
moat db get src_spkg       # smoke: table exists
```

---

## 7. Registration — `moat/db/_cfg.yaml`

Append to the `schemas:` list (loads models into `Base.metadata`):

```yaml
  - moat.db.src.model
  - moat.db.src.model_
```

(The `model_` import resolves the `relationship` wiring, as for the other
domains.) No `CfgStore.with_` unless we later add runtime config — we
don’t, per the seeding decision.

`moat/db/src/__init__.py`: one-line docstring only (like `box`).

---

## 8. Files to create / modify

```
NEW   moat/db/src/__init__.py
NEW   moat/db/src/model.py
NEW   moat/db/src/model_.py
NEW   moat/db/src/_main.py
NEW   moat/db/src/_git.py
NEW   moat/db/src/_seed.yml
NEW   moat/db/alembic/versions/<hex>_add_src_tracking.py
NEW   moat/db/alembic/versions/<hex>_seed_src_roles.py
MOD   moat/db/_cfg.yaml                         # +2 schema entries
NEW   tests/moat_db_src/__init__.py
NEW   tests/moat_db_src/conftest.py
NEW   tests/moat_db_src/test_smoke.py
NEW   tests/moat_db_src/test_spkg.py
NEW   tests/moat_db_src/test_roles.py            # archive-role + branch-role
NEW   tests/moat_db_src/test_archive.py          # remote CRUD + single-default
NEW   tests/moat_db_src/test_branch.py           # local-branch + status stamping
```

---

## 9. Tests (`tests/moat_db_src/`)

Clone the `rain` conftest pattern (shared-session SQLite via
`Base.metadata.create_all`, per-test wipe of `src_*` rows, `engine`
fixture, async CLI driver wrapping `moat.src.test.run`):

- **`conftest.py`** — `_db_url` (session), `db_url` (wipes `src_*`),
  `engine`, `async def src(db_url)` returning `R(*args, ee=0)` that calls
  `run("-s","moat.db.url",url,*args,expect_exit=ee)`. Cheap ORM-direct
  seed fixtures for roles.
- **`test_smoke.py`** — `await R("src","--help")` exits 0 and lists
  `list`/`add`/`import`/`archive`/`branch`/`at`.
- **`test_spkg.py`** — `add SPKG`; `at SPKG list` detail; duplicate `add`
  exits 1; `at <unknown>` errors pointing at `add`; `set`/`delete`.
- **`test_roles.py`** — `archive`/`branch` registry CRUD (`list`/`add`/
  `show`/`set`/`delete`); uniqueness; `--abstract/--real` toggle.
- **`test_archive.py`** — `at SPKG remote` CRUD; `--default`
  single-per-spkg invariant (setting a second default clears the first);
  role-required-on-create; role immutability post-create.
- **`test_branch.py`** — `at SPKG branch` CRUD; `--status @file` and
  `--status -` (clear); `updated` stamped on status/commit change and
  untouched otherwise; `--role` assigns/clears.
- **`test_import_export.py`** — build throwaway git repos with `git init` +
  `git remote add` (with fake fetch/push URLs) + a commit in `tmp_path`;
  drive `import`/`export` through `R(...)`. Covers: top-level `import`
  creates SPKG + archives + branches; refusal when SPKG exists; `at SPKG
  import` re-sync updates urls/commits, preserves `status`/`role`/
  `comment`; `--prune` drops vanished remotes/branches; role-resolution
  tiers (`--role` beats git-config beats heuristic); heuristic branches
  (`origin`→upstream, fetch-only→fork, push+`--mirror`→mirror,
  push−`--mirror`→local); `moat.src.roles.X` git-config honored; `export`
  clones default archive, adds other remotes, restores branches (from
  origin ref or `commit`), refuses non-empty/dirty `--dest`; round-trip
  topology stability (excluding `status`). Uses a local bare repo as the
  "default archive" URL so `git clone` needs no network.

Representative driver calls:
```python
await R("src","list")
await R("src","add","moat-util","--comment","x")
await R("src","archive","add","upstream","--rank","1")
await R("src","branch","add","main")
await R("src","at","moat-util","remote","add","github",
        "--role","upstream","--url","https://example/x.git","--default")
await R("src","at","moat-util","branch","add","devel","--status","ok")
await R("src","at","nope","list", ee=1)        # unknown SPKG
```

---

## 10. Implementation checklist (do in order)

1. **Branch/prep:** be on a populated topic branch off `main`.
2. **Skeleton:** create `moat/db/src/__init__.py` (docstring).
3. **Models:** write `model.py` (five classes, `__tablename__` overrides,
   columns, `dump()`). No relationships yet.
4. **Wire relationships + apply:** write `model_.py`.
5. **Register:** add the two `schemas:` lines to `moat/db/_cfg.yaml`.
6. **Sanity-import:** `python -c "import moat.db.util as u; u.load(u.attrdict({'schemas':['moat.db.src.model','moat.db.src.model_'],'url':'sqlite://'}))"`
   — must populate `Base.metadata` with the five `src_*` tables.
7. **Schema migration:** `moat db migrate rev "Add src package/archive/branch tracking"`,
   hand-edit the generated file to the `<hex>_add_src_tracking.py` form,
   prune stray autogen noise. `moat db migrate check` ⇒ clean.
8. **Seed file:** write `moat/db/src/_seed.yml`.
9. **Seed migration:** `moat db migrate rev "Seed src roles"`; replace its
   body with the `_seed.yml`-reading insert/downgrade logic
   (`<hex>_seed_src_roles.py`).
10. **Apply:** `moat db migrate update`; verify rows landed.
11. **Git-interplay module:** add `moat/db/src/_git.py` with the shared
    role-resolver (three-tier precedence) and the `import`/`export` workers
    (discovery via `git` plumbing; `export` via `git clone` + `git remote add`
    + `git branch`). Pure stdlib + `moat.util.exec.run`; **no** `moat.src`
    imports. Unit-test the resolver separately from the CLI.
12. **CLI:** write `moat/db/src/_main.py` per §2 — top group + `list`/`add`/
    `import` leaves, `archive`/`branch`/`at` groups, and leaves under each
    (`remote`/`branch`/`set`/`delete`/`import`/`export`). Pickup is automatic
    via `load_subgroup(prefix="moat.db.src")`.
13. **Manual smoke:** `moat db src list`; `moat db src add moat-util`;
    `moat db src at moat-util remote add …`; `moat db src at moat-util
    branch add …`; `moat db src import ./moat-util --name moat-util`;
    `moat db src at moat-util export --dest /tmp/x`.
14. **Tests:** create `tests/moat_db_src/` per §9; iterate green.
15. **Lint/types:** `ruff check moat/db/src tests/moat_db_src`;
    `mypy moat/db/src` if the repo type-checks db domains (match `rain`).

---

## 11. Decisions / risks / deferred

- **`at SPKG` scoping** resolves the earlier `branch` dual-dispatch problem
  cleanly: top-level `branch` = BranchRole registry, `at SPKG branch` =
  LocalBranch. Separate click groups ⇒ no name clash, no mixed-option
  leaves, no sentinel mode-detection. `at` assumes the SPKG exists and
  directs unknown SPKGs to `moat db src add SPKG`.
- **Explicit `list` verb** (instead of “omit the name to enumerate”) is a
  deliberate departure from `box`/`thing`, forced by the no-optional-
  positional rule. Enumeration is always `list`; detail is `show NAME`.
- **SPKG `set`/`delete`** are included (under `at SPKG`), no longer
  deferred — they fell out of the `at` redesign. `delete` cascades to the
  SPKG’s archives and branches.
- **Single `--default` archive per SPKG** — enforced in `archive_apply`
  (code), not via a partial DB index, for portability. Confirm desired.
- **`Archive.role` immutable after create** — matches `ThingTyp`-on-`Thing`
  stance; keeps role-history meaningful. Confirm (vs. allow re-role).
- **`Archive.api` free-form** with soft validation (warn, don’t fail) so
  novel forges don’t need a migration. Confirm.
- **Tags** are not tracked (request listed branches only; `moat.src` knows
  both). Defer.
- **Import/export are local-git round trips, NOT `moat.src`.** Deliberately
  narrower than the forge-move stack: no tokens, no remote-repo creation,
  no branch/tag deletion, no README rewriting. `import` touches no
  network; `export` only clones the default archive's URL. Implemented in a
  dedicated `moat/db/src/_git.py` with zero `moat.src` imports.
- **Role resolution is three-tier** (CLI `--role REMOTE=ROLE` >
  `moat.src.roles.<REMOTE>` git-config > heuristic). Heuristic yields
  `upstream`/`fork`/`mirror`/`local`; the latter two are therefore seeded
  (§5). Unresolved role ⇒ abort with guidance, never silent fallback.
- **`import` upserts, doesn't blind-insert.** Matching by `(spkg,name)`;
  vanished remotes/branches are reported, not deleted, unless `--prune`.
  `LocalBranch.status`/`role` and `Archive.comment` are preserved across
  re-sync (comment resets only if the URL changed).
- **`export` is not the inverse of `import`.** `status`/`role`/comments
  are DB-side annotations with no git representation and do not round-trip.
  Export deterministically rebuilds remote/branch *topology* from the DB.
- **`status` is DB-only** (confirmed): not written to the repo on export,
  not read on import; preserved across re-sync. Lives purely in
  `src_branch.status`.
- **Live forge sync** (populating the catalogue from `moat.src.api`
  queries of github/forgejo/radicle) remains out of scope for this
  iteration; the local-git import/export cover the common case. A future
  `moat db src at SPKG sync` could add it.
- **Out of scope:** migrating `moat.src`’s config-based role mapping into
  the DB; feeding `moat.src.move` from DB rows. Later work.
