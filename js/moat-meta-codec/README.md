# @moat/meta-codec

Metadata codec for MoaT messages — Node-RED encode/decode nodes.

<!-- synopsis -->

Encodes and decodes MoaT message metadata to/from the `MoaT` MQTT user property.
Elements are either UTF-8 strings (delimited by `/`) or arbitrary data
(delimited by `\`), where arbitrary data is CBOR-encoded then base85-encoded
using the btoa alphabet.

<!-- /synopsis -->

## Installation

```bash
npm install @moat/meta-codec
```

Requires Node.js ≥ 20.

## Usage in Node-RED

This package registers two Node-RED node types:

- **moat-meta-encode** — reads `msg.moat` and writes `msg.userProperties.MoaT`
- **moat-meta-decode** — reads `msg.userProperties.MoaT` and writes `msg.moat`

The `msg.moat` object has the following shape:

| Field  | Type     | Description                                   |
|--------|----------|-----------------------------------------------|
| `name` | string   | Sender name (defaults to `"NodeRed"`)         |
| `time` | number   | Epoch timestamp in seconds (defaults to now)   |
| `a`    | array    | Positional arguments                          |
| `kw`   | object   | Keyword arguments                             |

## Programmatic API

```javascript
import { encode, decode, encMsg, decMsg } from "@moat/meta-codec";

// Encode/decode metadata strings
const encoded = encode(["foo", 42, { key: "val" }]);
const decoded = decode(encoded);

// Encode/decode Node-RED messages
const msg = { moat: { name: "Sensor1", time: 1700000000, a: [25.5] } };
encMsg(msg);
// msg.userProperties.MoaT is now set

const msg2 = { userProperties: { MoaT: msg.userProperties.MoaT } };
decMsg(msg2);
// msg2.moat is now populated
```

## Wire format

The metadata string uses `/` to delimit UTF-8 string elements and `\` to
delimit arbitrary data elements. Arbitrary data is CBOR-encoded (canonical /
CDE) then base85-encoded (btoa alphabet). The first element must be a
non-empty string and is not prefixed with a delimiter.

## License

LGPL-3.0-or-later
