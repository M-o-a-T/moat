# Architecture — moat.lib.run

CLI entry-point orchestration: the top-level async Click command, runtime
setup (config/logging/`ctx.obj`), and **dynamic subcommand discovery**. This
is the dispatch spine of the whole `moat` command line.

All in `lib/run/__init__.py` (~1050 lines). Built on **asyncclick** (async
fork of Click).

## `main_` — the top-level async Click command

Decorated `@load_subgroup(cls=MainLoader, invoke_without_command=True,
add_help_option=False)` plus options (`-V/--verbose`, `-Q/--quiet`,
`-D/--debug`, `-l/--log`, `-c/--cfg`, `-h/--help`) and `@attr_args` (adds
`-s/--set name value` pairs). Body: guard double-invocation via
`ctx._moat_invoked`, merge any `current_cfg` into kwargs, call `wrap_main`,
then either print help or invoke `ctx.obj.moat.main_cmd(ctx)`.

## `wrap_main(...)` — the setup engine

Usable directly from tests (pass `wrap=True` to return the awaitable instead
of configuring logging). Steps:

1. Build/refresh `ctx.obj` (`attrdict`) + its `.moat` sub-dict; copy
   `sub_pre/sub_post/ext_pre/ext_post` (discovery prefixes) onto it.
2. Resolve `sub_pre` (defaults to `name`, or discover caller's `__package__`
   if `True`); `sub_post` defaults to `"_main.cli"`.
3. Create `CfgStore` (`CFG(name, preload=cfg, load_all=cfg_load_all,
   ext=ext_name)`) unless one passed; add `cfg_files`; call `CFG.with_("moat")`
   and `CFG.with_(name)` to pull in module defaults.
4. Configure logging from config (verbosity → `logging.root.level`; apply
   `--log` overrides; `logging.config.dictConfig`), then disable later
   `basicConfig`/`dictConfig`/`fileConfig` and mark `logging.root._MoaT`.
5. `process_args(...)` folds `-s/--set` overrides into the live config. Value
   prefixes: `~`=str, `=`=eval/special, `.`/`:`=Path, `^`=Proxy.
6. Honor `cfg.env.in_test(cfg)` hook if present.
7. Store `obj.cfg = cfg.result[name]`, `obj.logger`, `obj.stdout`,
   `obj.debug_loader`; attach `obj` to `ctx` (or, when `wrap`, return the
   `main.main` awaitable to drive manually).

## Command discovery — `Loader(AliasedGroup)` / `MainLoader(Loader)`

`load_subgroup(...)` decorator factory configures a Click group whose `cls`
is `partial(Loader, _util_sub_pre=…, _util_sub_post=…, _util_ext_pre=…,
_util_ext_post=…)`.

- `list_commands(ctx)` — extend Click's list by scanning the `sub_pre`
  namespace (`pkgutil.iter_modules` via `_namespaces()`), skipping `_`-prefixed
  names, probing each with `load_ext(sub_pre, name, *sub_post)`; also scan
  external extension packages via `list_ext(ext_pre)`.
- `_get_command(ctx, name)` — try built-ins, then
  `load_ext(ext_pre, name, *ext_post)` (external), then
  `load_ext(sub_pre, name, *sub_post)` (internal); on success call
  `CFG.with_(...)` to load that subcommand's `_cfg.yaml` defaults; rename to
  the requested alias.
- `get_command` adds **unique-prefix alias resolution** (matches
  starting-with; single match resolves; ambiguous fails).
- `MainLoader.invoke` forces the group's own callback (`main_`) to run even
  when a subcommand like `--help` is selected — setup happens exactly once.

`load_ext(name, *attr, err=)` — `importlib.import_module("{pre}.{name}.
{suffix segments}")` optionally `getattr`ing the trailing attribute; missing
modules return `None` unless `err`. `list_ext(name, func, pkg_only)` caches
discovered extension dirs. `this_load` `ContextVar` carries the originating
package so nested groups inherit sensible defaults.

## Argument parsing — `attr_args` / `process_args`

`attr_args` decorates a command to add `-s/--set` (combined) or legacy
`-v/-e/-p/-P` options accepting `(name, value)` pairs. `process_args`
interprets value prefixes, sorts by key depth when stable ordering matters,
and writes into either a supplied dict or directly into the global `CFG` via
`CFG.mod(Path, value)`.

## Net dispatch chain

`moat/__main__.py` → `moat/main.py:cmd()` →
`_cmd(sub_pre="moat", sub_post="_main.cli")` → `anyio.run` →
`main_.main(obj={moat:...})` (a `MainLoader` group) → on each subcommand,
`Loader._get_command` imports `moat.<pkg>._main.cli` (or external
`moat_<ext_pre>.<name>._main.cli`), pulls its `_cfg.yaml` via `CFG.with_`,
and recurses into that subgroup's own `sub_pre`/`sub_post`.

## Typical `_main.cli` shapes

- Template (`moat/src/_templates/moat/_main.py`): `@load_subgroup(prefix=…)`
  group with `@cli.command` leaves.
- Internal sub-pre at a sibling `command/` dir (`moat/kv/_main.py`):
  `@load_subgroup(sub_pre="moat.kv.command", sub_post="cli", ext_pre="moat.kv",
  ext_post="_main.cli")`.
- Leaf command module (`moat/kv/command/acl.py`): plain `@click.group`/
  `@click.command`; the exported `cli` is what the parent `Loader` imports.
