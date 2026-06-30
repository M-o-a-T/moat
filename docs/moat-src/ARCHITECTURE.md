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
  names, README templating, Radicle/local-git/github targets).
- **`_hooks/pre-commit`** — git hook installed by `apply_hooks()`.
- **`_templates/`** — scaffolding templates (`moat/_main.py`, `moat/__init__.py`,
  `Makefile`, `gitignore`, `test_basic_py`, `packaging/`) consumed by
  `apply_templates()` in `_main.py`.
- **`_util.py`** — `dash`/`undash` helpers between dotted and dashed names.

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
