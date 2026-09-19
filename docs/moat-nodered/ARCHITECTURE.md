# Architecture — moat.nodered

Node-RED plugin for encoding/decoding MoaT message metadata to/from MQTT user
properties, enabling Node-RED flows to participate in the MoaT messaging
ecosystem.

## Contents

A single npm package `@moat/meta-codec` (under `js/moat-meta-codec/`):

- **`lib/codec.js`** (~240 lines) — two Node-RED node types:
  `moat-meta-encode` and `moat-meta-decode`. Encoding produces a compact
  string: UTF-8 path elements separated by `/`, binary/CBOR elements
  separated by `\` and base85-encoded. Decoding reverses this. Populates/
  consumes `msg.moat` (with `name`, `time`, `delay`, `a`, `kw`) and
  `msg.userProperties.MoaT`.
- **`moat-meta-codec.html`** — Node-RED UI registration (editor palette,
  templates, help).
- **`package.json`** — declares dependencies (`base85-full`, `cbor2`),
  Node-RED node registration.

## Integration

Bridges Node-RED flows to MoaT's MQTT-based messaging by handling the `MoaT`
MQTT user-property convention. This is the **JavaScript counterpart** to
MoaT's Python-side metadata encoding (mirroring the path/meta codec in
`moat.lib.codec` / `moat.link.meta` — see `moat-lib-codec/ARCHITECTURE.md` and
`moat-link/ARCHITECTURE.md`).

## Entry points

Installed as a Node-RED node package; the `moat-meta-encode`/`moat-meta-decode`
nodes appear in the Node-RED palette. No Python CLI.
