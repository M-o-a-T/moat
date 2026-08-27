# Architecture — moat.src

Source-tree management subsystem ("This subpackage manages source code,"
`src/__init__.py`). Monorepo scaffolding, version tagging, forge migration,
and inspection tooling.

## Contents

- **`_main.py`** — `cli` group (`@load_subgroup(sub_pre="moat.src",
  sub_post="cli")`) with commands: `setup` (scaffold a new subcommand),
  `rerepo`/`move_repo` (forge migration), `tags`, `tag` (version tagging),
  `path`.
- **`_repo.py`** — `Repo` class for walking the monorepo's subpackages.
- **`build.py`, `dep-update.py`, `inspect.py`, `move.py`, `test.py`,
  `worktree.py`** — subcommand implementations imported lazily inside
  `_main.py` handlers (e.g. `from .move import mv_repos`).
- **`_cfg.yaml`** — defaults for repo-migration (forge API endpoints, branch
  names, README templating, Radicle/local-git/github targets, workspace
  creation toggle).
- **`_hooks/pre-commit`** — git hook installed by `apply_hooks()`.
- **`_templates/`** — scaffolding templates (`moat/_main.py`, `moat/__init__.py`,
  `Makefile`, `gitignore`, `test_basic_py`, `packaging/`) consumed by
  `apply_templates()` in `_main.py`.
- **`_util.py`** — `dash`/`undash` helpers between dotted and dashed names.

## Forge migration (`move.py`)

The `rerepo` command moves repositories from one forge (e.g. GitHub) to
one or more destinations (Codeberg, local git, Radicle).  The
:class:`RepoMover` class orchestrates each individual migration:

1. **`setup()`** — clones the source repo to a local bare cache, renames
   the default branch to ``main``.
2. **`move()`** — pushes to each configured destination.
3. **`finish()`** — creates/updates a ``migrated`` branch with a README
   pointing to the new location, optionally removes source branches/tags,
   and optionally creates a workspace.

### Auto-migrate updates

When the ``migrated`` branch already exists, `finish()` compares the
rendered README against the one on the branch and updates it if the
content changed (e.g. because a new destination was added).  The push
refspec for the ``migrated`` branch is ensured via
:meth:`RepoMover._ensure_push_refspec`, which checks
``git config --get-all remote.src.push`` before appending, preventing
duplicate refspecs on repeated runs.

### Workspace creation

Setting ``work.workspace: true`` in the config (or passing ``-w`` /
``--workspace`` on the command line) creates a non-bare working copy of
each migrated repository in ``<cache>/<name>-ws``.  The workspace shares
objects with the bare clone via ``git clone --shared``, so disk overhead
is minimal.

## How dynamic subcommand loading works (context)

`moat.src` is itself an example of the dispatch mechanism in
`moat.lib.run` (see `moat-lib-run/ARCHITECTURE.md`): `@load_subgroup` injects
a `Loader` that scans the `moat.src` namespace for `<name>.cli` targets and
pulls each one's `_cfg.yaml` via `CFG.with_`. The `moat src setup` command
*scaffolds* new `_main.py` files using the templates here, so newly-created
subcommands slot straight into the same discovery scheme.

## Entry points

`moat src {setup,tags,tag,rerepo,move_repo,path,…}` (`src/_main.py`). Version
tagging: `./mt src tag -s moat.X.Y -m` (minor) / `-M` (major); patch versions
allocated automatically at build time.
