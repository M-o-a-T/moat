# Architecture — moat.util

Cross-cutting utility library used "throughout MoaT (and beyond)"
(`util/__init__.py:5`). The foundational layer nearly every other subsystem
imports from.

## Architecture

`util/__init__.py` is a **lazy-loading facade**. It maps ~90 public names to
source modules via an `_imports` dict and implements `__getattr__` to
import-on-first-access, caching the result. Avoids eager-loading everything.

## Key exports (with source files)

| Export | File | Purpose |
|---|---|---|
| `attrdict` | `dict.py` | Dict with attribute access, path-based get/set/delete (`get_`, `set_`, `update_`, `delete_`), recursive `_post` dirty-flagging for config post-processing. Central to `moat.lib.config`. |
| `combine_dict`, `merge` | `dict.py`, `_merge.py` | Recursive, non-destructive dict merge (first value wins). |
| `CtxObj` | `ctx.py` | Abstract base making `async with obj` delegate to an `@asynccontextmanager _ctx()` method. Used by `moat.mcp.Service`, `moat.bus.backend.BaseBusHandler`, etc. |
| `ValueEvent` | `event.py` | One-shot awaitable value/error for inter-task sync (inspired by `threading.Event`). |
| `Queue`, `Lockstep`, `DelayedRead/Write` | `queue.py` | Queues atop `anyio` memory streams (trio/anyio dropped plain queues). Flow-controlled variants. |
| `MsgReader`, `MsgWriter` | `msg.py` | Stream messages to/from files using pluggable codecs (`moat.lib.codec`). |
| `yload`, `yprint`, `yformat`, `yaml_repr` | `yaml.py` | YAML load/dump with custom representers for `Path`, `attrdict`, proxies. ruyaml/ruamel. |
| `NotGiven` (= `Ellipsis`) | `__init__.py:15` | Sentinel for "no value given," used pervasively. |
| `import_`, `load_from_cfg` | `impl.py` | Dynamic module import by dotted path; config-driven object instantiation. |
| `ungroup`, `ExpectedError`, `run_no_exc` | `exc.py` | Unwrap single-element exception groups; suppress expected errors. |
| `srepr`, `val2pos`, `pos2val` | `misc.py` | Compact repr; linear interpolation helpers. |
| `get_part`, `set_part`, `enc_part` | `part.py` | Walk/modify nested mappings; partial encoding for command interpreters. |
| `gen_ssl`, `run_tcp_server` | `server.py` | SSL context generation; simple TCP server wrapper. |
| `Cache`, `NoLock`, `OptCtx`, `digits`, `num2byte/byte2num`, `num2id` | `impl.py` | Misc primitives (LRU-ish cache, null context, number↔bytes, base-N IDs). |

## CLI

`util/_main.py` registered as `moat.util` via `load_subgroup`: `to` (time-until
calculation), `convert` (cross-format file converter: json/yaml/cbor/msgpack),
`path` (path encode/decode), `cfg` (dump config values).

## Integration

Imported everywhere — `attrdict` and `NotGiven` are ubiquitous; `CtxObj` is
the async-context-manager base for services and handlers; `combine_dict`/
`merge` drive config assembly; `yload`/`yprint` handle all YAML; `ValueEvent`
and `Queue` are the primary synchronization primitives.
