(moat-top)=
# The MoaT: An opinionated monorepo

The MoaT is a rather large :term:`monorepo`, aspiring to be a one-stop shop
for the daily practice of at least one person (hint: the primary author),
hence the "Master of all Things" part.

It's also, historically, the swamp around a castle … into which people
tossed stuff they wanted to get rid of or no longer think about, and which
needed to be dredged periodically.

This codebase does have some relationship to all of the above.

{.glossary}
monorepo
: A repository that contains many somewhat-interdependent parts,
  as opposed to many repositories with one part each which refer to
  each other.
  <br />
  The reason why the MoaT is a monorepo is explained in [the
  History section](history).

## Opinions and Standards

The MoaT is admittedly a somewhat opinionated codebase.
The plus side is that we don't need to think about which mechanism to select
when a single one is used pretty much everywhere.

### Attributes

We like dictionaries that behave like objects. Yes typing those gets
interesting, but dicts with random keys (or not) have the same problem.

### Data Serialization

We like CBOR. Yes it has its faults but at least it's regular, self-describing,
and self-delimiting. It can even be streamed, something which MoaT currently
doesn't support.

We like YAML, much for the same reasons.

There is no TOML or JSON in the MoaT codebase, other than `pyproject.toml`
of course.


## Parts included

(moat-top-link)
### The Link

[MoaT-Link](moat-link-top) is a client/server architecture on top of MQTT. It
uses [MoaT-CMD](moat_lib_cmd_top) as a data link to a background
server that operates as message forwarder and persistent data storage
(including history).

MoaT-Link supports a variety of clients for other services. Some of these
are still using in [MoaT-KV](moat_top_kv).

All MoaT-Link messages are encoded using CBOR. On MQTT they are tagged
with a user property that records who sent it when.


#### Persistency, Redundancy

There can be multiple MoaT-Link servers. Clients automatically reconnect
when one of them disconnects or becomes unresponsive.

Planned: [support for multiple MQTT servers](todo-link-mqtt).


#### Error handling

In a system that aspires to be reliable, misbehaving code needs to record
that it failed. MoaT-Link comes with a wrapper that auto-creates a problem
report, or deletes it when the problem no longer occurs.

Of course if a computer fails then there's nobody to send an error.
MoaT-Link also has a keepalive mechanism that can automatically notify
you when something goes down.


#### Data Schema

Any large system suffers from data rot. An extension to MoaT-Link (planned)
describes every message with a JSON schema and records mismatches.


### Legacy code

(moat-top-kv)
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
