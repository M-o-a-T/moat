# Architecture — moat.lib.path

`Path`/`PathElem` — the hierarchical, typed addressing primitive used
throughout MoaT. Lives in `lib/path/_impl.py` (~38 KB).

## Role

Paths are the universal identifier for data locations, config keys, RPC
command addresses, and MQTT topic mapping. Unlike flat strings, a `Path` is a
sequence of typed `PathElem`s supporting shortening/lengthening and root
anchoring.

## Key types

- **`Path`** — ordered sequence of `PathElem`s; immutable-ish, supports
  concatenation (`+`), indexing, equality/hash. Carries optional root info.
- **`PathElem`** — a single typed path segment.
- **`PathShortener` / `PathLongener`** — compress/decompress path prefixes.
  Long paths are shortened by factoring out repeated leading segments against
  a table; `PathLongener` reverses this. Critical for compact wire encoding
  (e.g. MoaT-Link `Node.dump`/`load`, MQTT topic reconstruction).
- Roots — anchor a path to a named namespace (e.g. `:R` for MoaT-Link root
  data, `:R.run` for transient data).

## Consumers

- `moat.lib.run` — `attr_args`/`process_args` parse `-s path value` into
  `Path`s.
- `moat.lib.config` — `CfgStore.mod`/`get_`/`set_` operate on `Path`.
- `moat.lib.rpc` — commands are addressed by `Path`; `RootCmd`/`DirCmd`
  trees map paths to handlers.
- `moat.link` — backend MQTT topics derive from `Path.slashed2()`; `Node`
  trees are keyed by paths; `MsgMeta` carries origin paths.
- `moat.modbus` — `dev/link.py` uses `src`/`dest` `Path`s to map registers to
  link topics.

## Conversion

`Path` ↔ MQTT slashed topic string (`slashed2`); `Path` ↔ dotted config key.
Wildcard forms (`+`, `#`, ranges) used by `moat.link.NodeFinder` and KV
matching — see `moat-link/ARCHITECTURE.md` and `moat-kv/ARCHITECTURE.md`.
