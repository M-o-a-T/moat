# Architecture — moat.lib.config

Hierarchical YAML configuration: layered loading, `$base` inheritance,
deferred per-package registration, and live-update monitoring. Almost every
MoaT subsystem declares defaults via a `_cfg.yaml` and registers itself at
import.

## Files

- `__init__.py` — lazy facade. `CFG`, `CfgStore`, `current_cfg`,
  `load_yaml`, `monitor`, `register` resolve on first access via
  `__getattr__` → `import_module(".{_imports[attr]}", __name__)`, avoiding
  circular imports.
- `_impl.py` — core: `CfgStore`, `CFG_` singleton, `default_cfg`, `monitor`.
- `base.py` — pydantic `BaseModel` (extra="allow", validate_assignment,
  dynamic field addition via `DecomposedModel`).
- `_reg.py` — deferred registration: global `to_process` set drained by
  `CfgStore.redo()`.

## Layer precedence (first wins)

CLI args → `preload` ctor arg → explicit config files (`add()`) → default
config files → per-package `_cfg.yaml` "static" data. Layers combined via
`combine_dict` (recursive, non-destructive, first-value-wins; see
`moat.util.dict`).

## CfgStore (`_impl.py`)

Class-level shared state: `static` (defaults pulled from modules'
`_cfg.yaml`), `env` (environment-derived), `updated` counter, `known`
(`WeakSet` of all live stores for background re-sync).

- `add(path)` — load & parse YAML (`load_yaml` resolves `$base` via
  `get_base`), append to `self.cfg`, flag `_redo`.
- `mod(path, value)` — record a manual override at a `Path`; `NotGiven`
  deletes. Flags `_redo`.
- `redo()` — drain pending `to_process` registrations, then loop ≤8 passes:
  combine `preload`+`env`+files+`static`, apply manual `args`, resolve
  relative `Path` refs (`deref`), `merge` into `_result` until no
  `NotGiven` placeholders remain. Calls `notify()`.
- `with_(path)` (classmethod) — walk dotted module path segments, import
  each, read that package's `_cfg.yaml` into `Cls.static`, pop `$root`
  remapping, bump `updated`, trigger `redo()` on all known stores. This is
  how submodules declare defaults.
- `__getattr__`/`__getitem__`/`__contains__` force `maybe_redo()` then read
  `self._result`.

## CFG singleton (`CFG_` instance)

Proxies attr get/set/del to the store bound in the `current_cfg` `ContextVar`
(`__getattr__` → `_get_current_cfg_attr`). Set up via `CFG(...)` (sets
`current_cfg`) or `CFG.set_real_cfg(...)`. `CFG.with_config_(cfg)` swaps
configs (context manager). `CFG.with_(...)` ensures a submodule's defaults are
loaded. `CFG.set_env_(key,value)` mutates the shared environment.

## Registration flow

1. Each `moat/<pkg>/__init__.py` calls
   `from moat.lib.config import register as _register; _register(__name__)`
   — just adds the dotted name to `to_process` (deferred to avoid circular
   imports).
2. `wrap_main()` (`moat.lib.run`) creates `CFG(name, preload=..., load_all=...,
   ext=...)` and calls `CFG.with_("moat")` + `CFG.with_(caller)`.
3. When a subcommand loads, `Loader._get_command` calls `CFG.with_("moat.<pkg>")`,
   which walks the path and merges each segment's `_cfg.yaml`.
4. `$root:` top-level keys in a `_cfg.yaml` are hoisted to the global static
   root; flat keys populate the package's subtree.

## Default-file discovery (`default_cfg`)

Respects `XDG_CONFIG_HOME`, `~/.config/<name>/config.yaml`,
`~/.<name>.yaml`, `/etc/<name>/<name>.yaml`, `<NAME>_CFG`/`CFG` env vars. A
`TEST` flag redirects to `tests/cfg/<name>.yaml`. `load_all` controls
True=all / False=first-found / None=skip.

## Live monitoring (`monitor`)

Context manager + async iterator. Patches the watched `attrdict`'s
`updated_` to set an `anyio.Event`; iterating awaits the event (debounced),
yielding the possibly-mutated config subtree.
