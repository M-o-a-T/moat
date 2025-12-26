(moat-top)=
# The MoaT: An opinionated monorepo

```{include} ../README.md
:start-after: % start main
:end-before: % end main
```

The MoaT aspires to be a one-stop shop for the daily practice of at least
one person (hint: the primary author), hence the "Master of all Things"
part.

Historically, a moat is the ditch around a castle … into which people
tossed stuff they wanted to get rid of or no longer think about, and which
needed to be dredged periodically. This codebase admittedly

We'll ignore a moat's secondary function of keeping unwanted people out
of the castle, except to request to please adhere to our [Code of Conduct](common/CONDUCT).

{.glossary}
monorepo
: A repository that contains many somewhat-interdependent parts,
  as opposed to many repositories with one part each which refer to
  each other.
  <br />
  The reason why the MoaT is a monorepo is explained in [the
  History section](history).

## [Project Information](common/index.md)

Start here if you have no idea what this is all about and want the bird's
eye view.

Also, the usual: Community guidelines, contribution guide, code and
documentation style, and all that.

## Parts included

### [The Link](moat-link/index.md)

```{include} ../packaging/moat-link/README.md
:start-after: % start synopsis
:end-before: % end synopsis
```

#### [Server](moat-link-server/index.md)

```{include} ../packaging/moat-link-server/README.md
:start-after: % start synopsis
:end-before: % end synopsis
```

#### [Web Frontend](moat-link-web/index.md)

```{include} ../packaging/moat-link-web/README.md
:start-after: % start synopsis
:end-before: % end synopsis
```

### [MicroPython Support](moat-micro/index.md)

```{include} ../packaging/moat-micro/README.md
:start-after: % start synopsis
:end-before: % end synopsis
```

### Configuration

% ```{include} ../packaging/moat-lib-config/README.md
% :start-after: % start synopsis
% :end-before: % end synopsis
% ```

See `moat.util.config`.

### [Command Line](moat/index.md)

```{include} ../packaging/moat/README.md
:start-after: % start synopsis
:end-before: % end synopsis
```

### [Modbus](moat-modbus/index.md)

```{include} ../packaging/moat-modbus/README.md
:start-after: % start synopsis
:end-before: % end synopsis
```

#### [Device Registry](moat-modbus-dev-_data/index.md)

```{include} ../packaging/moat-modbus-dev-_data/README.md
:start-after: % start synopsis
:end-before: % end synopsis
```

### More Parts


#### [Codec support buffer](moat-lib-codec/index.md)

```{include} ../packaging/moat-lib-codec/README.md
:start-after: % start synopsis
:end-before: % end synopsis
```

#### [GPIO](moat-lib-gpio/index.md)

```{include} ../packaging/moat-lib-gpio/README.md
:start-after: % start synopsis
:end-before: % end synopsis
```

#### [PID Controller](moat-lib-pid/index.md)

```{include} ../packaging/moat-lib-pid/README.md
:start-after: % start synopsis
:end-before: % end synopsis
```

#### [Priority Map](moat-lib-priomap/index.md)

```{include} ../packaging/moat-lib-priomap/README.md
:start-after: % start synopsis
:end-before: % end synopsis
```

#### [Ring buffer](moat-lib-ring/index.md)

```{include} ../packaging/moat-lib-ring/README.md
:start-after: % start synopsis
:end-before: % end synopsis
```

### Database

#### [Database Core](moat-db/index.md)

```{include} ../packaging/moat-db/README.md
:start-after: % start synopsis
:end-before: % end synopsis
```

#### [Things](moat-db-thing/index.md)

```{include} ../packaging/moat-db-thing/README.md
:start-after: % start synopsis
:end-before: % end synopsis
```

#### Networking

% ```{include} ../packaging/moat-db-network/README.md
% :start-after: % start synopsis
% :end-before: % end synopsis
% ```

See `moat.kv.inv`. Redesigning to be part of the MoaT database of
things is TODO.

#### [Labels](moat-db-label/index.md)

```{include} ../packaging/moat-db-label/README.md
:start-after: % start synopsis
:end-before: % end synopsis
```

#### [Boxes](moat-db-box/index.md)

```{include} ../packaging/moat-db-box/README.md
:start-after: % start synopsis
:end-before: % end synopsis
```

### [Energy Management](moat-ems/index.md)

```{include} ../packaging/moat-ems/README.md
:start-after: % start synopsis
:end-before: % end synopsis
```

#### [Battery control](moat-ems-battery/index.md)

```{include} ../packaging/moat-ems-battery/README.md
:start-after: % start synopsis
:end-before: % end synopsis
```

#### [Inverter control](moat-ems-inv/index.md)

```{include} ../packaging/moat-ems-inv/README.md
:start-after: % start synopsis
:end-before: % end synopsis
```

#### [Scheduling](moat-ems-sched/index.md)

```{include} ../packaging/moat-ems-sched/README.md
:start-after: % start synopsis
:end-before: % end synopsis
```

### [Modbus Devices](moat-dev/index.md)

```{include} ../packaging/moat-dev/README.md
:start-after: % start synopsis
:end-before: % end synopsis
```

#### [SEW inverters](moat-dev-sew/index.md)

```{include} ../packaging/moat-dev-sew/README.md
:start-after: % start synopsis
:end-before: % end synopsis
```

#### [Heating](moat-dev-heat/index.md)

```{include} ../packaging/moat-dev-heat/README.md
:start-after: % start synopsis
:end-before: % end synopsis
```

### [The Data Bus](moat-bus/index.md)

```{include} ../packaging/moat-bus/README.md
:start-after: % start synopsis
:end-before: % end synopsis
```


### Legacy


#### [Key-Value Storage](moat-kv/index.md)

```{include} ../packaging/moat-kv/README.md
:start-after: % start synopsis
:end-before: % end synopsis
```

#### [Akumuli (time-based storage) backend](moat-kv-akumuli/index.md)

```{include} ../packaging/moat-kv-akumuli/README.md
:start-after: % start synopsis
:end-before: % end synopsis
```

#### [Calendar access](moat-kv-cal/index.md)

```{include} ../packaging/moat-kv-cal/README.md
:start-after: % start synopsis
:end-before: % end synopsis
```

#### [GPIO](moat-kv-gpio/index.md)

```{include} ../packaging/moat-kv-gpio/README.md
:start-after: % start synopsis
:end-before: % end synopsis
```

#### [Home Assistant](moat-kv-ha/index.md)

```{include} ../packaging/moat-kv-ha/README.md
:start-after: % start synopsis
:end-before: % end synopsis
```

:::{note}
MoaT uses CBOR. MoaT-KV uses Msgpack. Home Assistant and much of the
rest of the MQTT universe insist on strings like `ON` or `off`, or JSON.

We'd rather not do that.
:::

#### [Inventory](moat-kv-inv/index.md)

```{include} ../packaging/moat-kv-inv/README.md
:start-after: % start synopsis
:end-before: % end synopsis
```

#### [KNX](moat-kv-knx/index.md)

```{include} ../packaging/moat-kv-knx/README.md
:start-after: % start synopsis
:end-before: % end synopsis
```

#### [1Wire](moat-kv-ow/index.md)

```{include} ../packaging/moat-kv-ow/README.md
:start-after: % start synopsis
:end-before: % end synopsis
```

#### [Wago](moat-kv-wago/index.md)

```{include} ../packaging/moat-kv-wago/README.md
:start-after: % start synopsis
:end-before: % end synopsis
```

#### [MQTT](moat-mqtt/index.md)

```{include} ../packaging/moat-mqtt/README.md
:start-after: % start synopsis
:end-before: % end synopsis
```

#### [Node-RED](moat-nodered/index.md)

```{include} ../packaging/moat-nodered/README.md
:start-after: % start synopsis
:end-before: % end synopsis
```


### Libraries

(moat-top-lib-cmd)=
#### [MoaT-Cmd](moat-lib-cmd/index.md)

This library is our answer to the "how do I do bidirectional RPC calls over
any data link? Oh, error forwarding and flow-controlled streaming and
cancellation would be nice to have too" question.

```{include} ../packaging/moat-lib-cmd/README.md
:start-after: % start synopsis
:end-before: % end synopsis
```

#### [Codec Buffer](moat-lib-codec/index.md)

```{include} ../packaging/moat-lib-codec/README.md
:start-after: % start synopsis
:end-before: % end synopsis
```

#### [Diffie-Hellman](moat-lib-diffiehellman/index.md)

```{include} ../packaging/moat-lib-diffiehellman/README.md
:start-after: % start synopsis
:end-before: % end synopsis
```

#### [GPIO](moat-lib-gpio/index.md)

```{include} ../packaging/moat-lib-gpio/README.md
:start-after: % start synopsis
:end-before: % end synopsis
```

#### [PID Controller](moat-lib-pid/index.md)

```{include} ../packaging/moat-lib-pid/README.md
:start-after: % start synopsis
:end-before: % end synopsis
```

#### [Priority Map](moat-lib-priomap/index.md)

```{include} ../packaging/moat-lib-priomap/README.md
:start-after: % start synopsis
:end-before: % end synopsis
```

#### [Ring Buffer](moat-lib-ring/index.md)

```{include} ../packaging/moat-lib-ring/README.md
:start-after: % start synopsis
:end-before: % end synopsis
```

#### [Victron Support](moat-lib-victron/index.md)

```{include} ../packaging/moat-lib-victron/README.md
:start-after: % start synopsis
:end-before: % end synopsis
```

### Random helpers

{#moat-top-util}
#### [Utilities](moat-util/index.md)

[moat-util](moat-util) is a collection of code that makes life easier.
Or at least typing. :class:`attrdict` in particular is a dangerous but
much-too-useful thing that allows for typing one dot instead of the ``["…"]``
combination. It also contains a wrapper for multi-level command-line-based
programs, using *asyncclick* under the hood, and some date/time handling,
conversion between yaml and CBOR and msgpack and … you get the idea.

```{include} ../packaging/moat-util/README.md
:start-after: % start synopsis
:end-before: % end synopsis
```

#### [Source Management](moat-src/index.md)

```{include} ../packaging/moat-src/README.md
:start-after: % start synopsis
:end-before: % end synopsis
```

#### [3D CAD Support](moat-cad/index.md)

```{include} ../packaging/moat-cad/README.md
:start-after: % start synopsis
:end-before: % end synopsis
```


```{toctree}
:maxdepth: 4
:hidden:

moat-link/index
moat-lib
moat-micro/index
moat/index
moat-modbus/index
moat-db/index
moat-ems/index
moat-dev/index
moat-bus/index
moat-kv/index
moat-util/index
moat-src/index
moat-cad/index
common/index
```
