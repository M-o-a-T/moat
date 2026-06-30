# Architecture — moat.lib.codec

Pluggable (de)serialization framework. `Codec` ABC + `Extension` registry;
multiple wire formats; MoaT-specific compact variants.

## Files

- `_base.py` — `Codec` ABC and `Extension` registry.
- Concrete encoders: `_cbor.py` (CBOR), `msgpack.py`, `_moat_cbor.py`
  (StdCBOR — compact, used for metadata), `_moat_msgpack.py`, `json.py`,
  `jsonvalue.py`, `yaml.py`, `utf8.py`, `binary.py`, `bool.py`, `null.py`,
  `noop.py`.
- `errors.py` — `NoPathError`, `RemoteError`; registers all standard
  exceptions via `as_proxy` so they survive transport.
- `__init__.py` — `get_codec(name)` resolver.

## Codec contract (`_base.py`)

`Codec` defines `encode`/`decode`/`feed`/`__next__`/`unfeed` for both **block**
and **incremental / incremental-interleaved** decoding. This allows streaming
decoders that yield decoded objects as bytes arrive (essential for the
reliable stream layer). `Extension` registers type→encoder/key and
key→decoder mappings, so custom types (proxies, exceptions) round-trip.

## Name resolution (`get_codec`)

`get_codec(name)` (`__init__.py`):
- Bare names map to `moat.lib.codec.<name>` (e.g. `"cbor"`→`moat.lib.codec.cbor`).
- `std-*` names map to `moat.lib.codec.moat_<suffix>` (e.g. `"std-cbor"`→
  `moat.lib.codec.moat_cbor`, `"std-msgpack"`→`moat.lib.codec.moat_msgpack`).

Available: `cbor`, `moat_cbor` (StdCBOR, used for `MsgMeta`), `moat_msgpack`,
`json`, `jsonvalue`, `utf8`, `binary`, `bool`, `null`, `noop`, `yaml`.

## Wiring

`stream/cbor.py` wires codecs onto `BaseMsg` for message framing over the
transport stack. `moat.link` configures one codec for payloads
(`cfg.backend.codec`, default `std-cbor`) and a fixed `std-cbor` for metadata
internals. Gates select a codec per destination side (source side is always
`std-cbor`).

## Proxies & exceptions

Objects cross the codec boundary by registered name via `moat.lib.proxy`
(see `moat-lib-proxy/ARCHITECTURE.md`). `codec/errors.py` registers all
standard exceptions this way (`as_proxy("_rErrS", SilentRemoteError)`, …) so a
raised exception on one side re-materializes on the other.

See `moat-util/ARCHITECTURE.md` for `MsgReader`/`MsgWriter` (file streaming
using these codecs).
