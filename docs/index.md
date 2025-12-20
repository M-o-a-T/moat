(moat-top)=
# The MoaT: An opinionated monorepo

The MoaT aspires to be a one-stop shop for the daily practice of at least
one person (hint: the primary author), hence the "Master of all Things"
part.

Historically, a moat is the ditch around a castle … into which people
tossed stuff they wanted to get rid of or no longer think about, and which
needed to be dredged periodically. This codebase admittedly

We'll ignore a moat's secondary function of keeping unwanted people out
of the castle, except to request to please adhere to our [Code of Conduct](common/conduct.html).

{.glossary}
monorepo
: A repository that contains many somewhat-interdependent parts,
  as opposed to many repositories with one part each which refer to
  each other.
  <br />
  The reason why the MoaT is a monorepo is explained in [the
  History section](history).

## Parts included

### The Link

```{include} ../packaging/moat-link/README.md
:start-after: % start synopsis
:end-before: % end synopsis
```

#### Server

```{include} ../packaging/moat-link-server/README.md
:start-after: % start synopsis
:end-before: % end synopsis
```

### The RPC Library

```{include} ../packaging/moat-lib-cmd/README.md
:start-after: % start synopsis
:end-before: % end synopsis
```

### MicroPython Support

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

### Command Line

```{include} ../packaging/moat/README.md
:start-after: % start synopsis
:end-before: % end synopsis
```

### Modbus

```{include} ../packaging/moat-modbus/README.md
:start-after: % start synopsis
:end-before: % end synopsis
```

### More Parts


#### Codec support buffer

```{include} ../packaging/moat-lib-codec/README.md
:start-after: % start synopsis
:end-before: % end synopsis
```

#### GPIO

```{include} ../packaging/moat-lib-ring/README.md
:start-after: % start synopsis
:end-before: % end synopsis
```

#### Priority Map

```{include} ../packaging/moat-lib-priomap/README.md
:start-after: % start synopsis
:end-before: % end synopsis
```

#### Ring buffer

```{include} ../packaging/moat-lib-ring/README.md
:start-after: % start synopsis
:end-before: % end synopsis
```

#### MQTT

```{include} ../packaging/moat-modbus/README.md
:start-after: % start synopsis
:end-before: % end synopsis
```

### Database


#### Things

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

#### Labels

```{include} ../packaging/moat-db-label/README.md
:start-after: % start synopsis
:end-before: % end synopsis
```

#### Boxes

```{include} ../packaging/moat-db-box/README.md
:start-after: % start synopsis
:end-before: % end synopsis
```

### Energy Management

```{include} ../packaging/moat-ems/README.md
:start-after: % start synopsis
:end-before: % end synopsis
```

#### Battery control

```{include} ../packaging/moat-ems-battery/README.md
:start-after: % start synopsis
:end-before: % end synopsis
```

#### Inverter control

```{include} ../packaging/moat-ems-inv/README.md
:start-after: % start synopsis
:end-before: % end synopsis
```

#### Scheduling

```{include} ../packaging/moat-ems-sched/README.md
:start-after: % start synopsis
:end-before: % end synopsis
```

### Modbus Devices

```{include} ../packaging/moat-dev/README.md
:start-after: % start synopsis
:end-before: % end synopsis
```

#### SEW inverters

```{include} ../packaging/moat-dev-sew/README.md
:start-after: % start synopsis
:end-before: % end synopsis
```

#### Heating

```{include} ../packaging/moat-dev-heat/README.md
:start-after: % start synopsis
:end-before: % end synopsis
```

### The Data Bus

```{include} ../packaging/moat-bus/README.md
:start-after: % start synopsis
:end-before: % end synopsis
```


### Legacy


#### Key-Value Storage

```{include} ../packaging/moat-kv/README.md
:start-after: % start synopsis
:end-before: % end synopsis
```

#### Akumuli (time-based storage) backend

```{include} ../packaging/moat-kv-akumuli/README.md
:start-after: % start synopsis
:end-before: % end synopsis
```

#### Calendar access

```{include} ../packaging/moat-kv-cal/README.md
:start-after: % start synopsis
:end-before: % end synopsis
```

#### GPIO

```{include} ../packaging/moat-kv-gpio/README.md
:start-after: % start synopsis
:end-before: % end synopsis
```

#### Home Assistant

```{include} ../packaging/moat-kv-ha/README.md
:start-after: % start synopsis
:end-before: % end synopsis
```

#### Inventory

```{include} ../packaging/moat-kv-inv/README.md
:start-after: % start synopsis
:end-before: % end synopsis
```

#### KNX

```{include} ../packaging/moat-kv-knx/README.md
:start-after: % start synopsis
:end-before: % end synopsis
```

#### 1Wire

```{include} ../packaging/moat-kv-ow/README.md
:start-after: % start synopsis
:end-before: % end synopsis
```

#### Wago

```{include} ../packaging/moat-kv-wago/README.md
:start-after: % start synopsis
:end-before: % end synopsis
```

### Legacy code

(moat-top-kv)=
#### MoaT-KV: key-value storage

[MoaT-KV]<moat-kv-top>` attempted to work around the limitations of the
:term:`CAP theorem` by noting that in most installations there's only one
side modifying any particular data item. Thus it attached an internal
message history to each node, and multiple server merged their changes
whenever they reconnected after a network break.

{.glossary}
CAP theorem
: The CAP (or Brewer's) theorem states that you can get at most two of
  (global) Consistency, Availability, and Partition tolerance.

MoaT-KV is in the process of getting replaced by MoaT-Link. The reasons
for the switch are detailed :ref:`here<moat_kv_why_not>`.


(moat-top-lib-kv-knx)=
##### knx

(moat-top-lib-kv-ow)=
##### 1wire

(moat-top-lib-kv-gpio)=
##### GPIO

(moat-top-lib-kv-akumuli)=
##### akumuli

(moat-top-lib-kv-cal)=
##### cal

(moat-top-lib-kv-ha)=
##### Home Assistant

MoaT interfaces with Home Assistant, using MQTT.

The KV part is concerned with assembling appropriate configuration.
Message translation is performed by a [MoaT-Link-Gate](link-gate-top)
instance.

:::{note}
We use CBOR. MoaT-KV used (or uses) Msgpack. Home Assistant and much of the
rest of the MQTT universe insist on strings like `ON` or `off`, or JSON.

We'd rather not do that.
:::

##### wago

### Libraries

(moat-top-lib-cmd)=
#### MoaT-Cmd

This library is our answer to the "how do I do bidirectional RPC calls over
any data link? Oh, error forwarding and flow-controlled streaming and
cancellation would be nice to have too" question.

:mod:``

### Random helpers

{#moat-top-util}
[moat-util](moat-util-top) is a collection of code that makes life easier.
Or at least typing. :class:`attrdict` in particular is a dangerous but
much-too-useful thing that allows for typing one dot instead of the ``["…"]``
combination. It also contains a wrapper for multi-level command-line-based
programs, using *asyncclick* under the hood, and some date/time handling,
conversion between yaml and CBOR and msgpack and … you get the idea.


## Opinions and Standards

The MoaT is admittedly a somewhat opinionated codebase.
The plus side is that we don't need to think about which mechanism to select
when a single one is used pretty much everywhere.

### Configuration

Python programmers have a love-hate relationship to dictionaries whose
elements can be addressed with dot syntax. The MoaT is no exception.

### Data Serialization

We like CBOR. Yes it has its faults but at least it's regular, self-describing,
and self-delimiting. It can even be streamed, something which MoaT currently
doesn't support.

We like YAML, much for the same reasons.

There is no TOML or JSON in the MoaT codebase, other than `pyproject.toml`
of course.
