(moat-link-ha)=
# The Link: Home Assistant Connector

```{include} ../../packaging/moat-link-ha/README.md
:start-after: % start main
:end-before: % end main
```

## Configuration

Home-Assistant device definitions are stored in MoaT-Link under the
configured prefix (default: `hass`).  Each device type (`light`,
`switch`, `binary_sensor`, `number`, `sensor`, `lock`) has its own
subtree; device entries are keyed by a 1–2 element path.

## Bridging to Home Assistant

There is no HA-specific gate driver; use the generic MQTT gate with a
conversion vector. HA speaks plain strings (`"on"`, `"12.5"`, JSON), so
each topic needs a codec translating between that and MoaT-Link values.

1. Store a codec for each payload shape:

   ```
   moat link codec set BOOL -e ENC.py -d DEC.py -i '"on"' True -o False '"off"'
   ```

   Encode/decode are Python snippets (`return value…`); the `-i`/`-o`
   pairs are mandatory test vectors (wire ⇄ value). Common shapes:
   `on`/`off` booleans, decimal-number strings, JSON blobs.

2. Collect them in a conversion vector, mapping (sub)paths to codecs:

   ```
   moat link conv ha add SKIP            # create the vector root
   moat link conv ha at switch.+.state add BOOL
   moat link conv ha at sensor.+.#.state add NUM
   ```

   Sub-paths may use the wildcards `+` (one element) and `#` (one or
   more); the most specific entry wins. Entries only apply to paths
   below them — the vector root's codec covers nothing — so spell out
   the shapes you bridge. A codec of `null` silently drops that path.

3. Run the gate:

   ```
   moat link gate ha set -d mqtt -S SRC -D DST -s codec .ha
   moat link gate ha run
   ```

   `SRC` is the bridged subtree in MoaT-Link; `DST` is the topic prefix
   on the broker, dotted (`home.ass.dyn`), pointing at HA's discovery
   prefix. The gate relays both directions; retained messages seed the
   initial state. If HA uses a broker of its own, add
   `-s backend.host HOST` (etc.).

The `config` nodes from `moat link ha set` announce the entities to HA;
the bridge then carries their `state` and `cmd` topics.

## CLI reference

```
moat link ha set TYPE PATH [-s key value…]  # add/modify a device
moat link ha get TYPE PATH                  # show a device
moat link ha get - -                        # list device types
moat link ha delete TYPE PATH               # delete a device
```

```{toctree}
:maxdepth: 2
:hidden:

api
```
