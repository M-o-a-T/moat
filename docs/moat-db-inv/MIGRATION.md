---
orphan: true
---

# Migration plan: `moat-kv-inv` → `moat.db.inv`

This document plans the move of the network inventory (`mt kv inv …`,
implemented in `moat/kv/inv/`) from DistKV to a relational database, via a
new `moat.db.inv` package built on `moat.db` (SQLAlchemy + Alembic).

It covers the SQL data structure, the package/refactoring work, and the
one-time data migration from DistKV. It is a **plan**: nothing here is
committed code yet. Items flagged *“decision”* are choices that should be
confirmed before implementation; the recommendation is given in each case.

## Goal

Replace the DistKV-backed inventory with a database-backed one, preserving
the existing concepts (VLANs, networks, hosts, interfaces/ports, cables,
wires, groups) while adopting the three design decisions below.

Out of scope for this initial plan: the Jinja template generator
(`host template`), the `find` path-finder, the EMS-side `moat/ems/inv/*`
code (unrelated — that’s an inverter, not this inventory), and the eventual
removal of `moat/kv/inv` (kept as the migration source until the migration
has run).

## Design decisions (given)

1. **The host’s direct network address becomes an interface.**
   The original code attached a network address straight to the host
   (`Host.net` + `Host.num`). This is replaced by a network *interface*
   owned by the host, with an **empty name** (`""`). On the command line
   this special interface is spelled `"."`.

2. **Hosts are Things.**
   The `host` table references a `moat.db.thing.model.Thing` row
   (`host.thing_id → thing.id`). A host is therefore a labelled, boxable,
   typed thing, plus the host-specific fields defined here.

3. **Addresses are stored as IPv6.**
   The database is assumed not to support IPv6 natively, so every network
   and interface address is stored as an **address + prefix** pair, using
   the IPv4-mapped IPv6 representation (`::ffff:a.b.c.d`) for IPv4. The
   original wording said “`BIGINT` + `TINYINT`”; a 128-bit IPv6 value
   does not fit a 64-bit `BIGINT`, so per Q5 the address column is
   realised as **`BINARY(16)`** (big-endian) with a `SMALLINT` prefix.
   On the Python side the value is exposed as an `ipaddress.IPv4Interface`
   (for IPv4-mapped addresses) or `ipaddress.IPv6Interface` (for native
   IPv6); networks analogously as `IPv4Network` / `IPv6Network`.

## Glossary: old term → new term

| DistKV (`moat/kv/inv`)         | `moat.db.inv`                       |
|--------------------------------|-------------------------------------|
| `Vlan`                         | `vlan` row                          |
| `Network`                      | `network` row                       |
| `Host`                         | `thing` + `host` row                |
| `Host.net` / `Host.num`        | `interface` row, `name=""`           |
| `HostPort`                     | `interface` row                     |
| `Wire`                         | *(see “Wires” decision)*            |
| `Cable`                        | `cable` row                         |
| `group` (named)                | `group` row + `host_group` M2M      |
| `Host.mac`                     | `mac` on the `""` interface         |
| path key `(bits, netnum)`      | `network.addr` + `network.prefix`    |
| path key `(server, tock)` cable| `cable.id` (surrogate)              |

## Derived decisions

These follow from the three given decisions but are not spelled out by
them. Status as of this revision:

- **D1 — accepted.** Wires are hosts (Thing type `wire`).
- **D2 — accepted (modified).** Store the concrete address *and* keep the
  host offset `num` on the interface.
- **D3 — deferred.** Master/slave co-existence: decide later; the
  `network.master_id` column is retained as a placeholder.
- **D4 — accepted (modified).** No separate `host.name`; the short name
  lives on `thing.name`.
- **D5 — accepted.** MAC as `BINARY(6)` → `netaddr.EUI`.
- **D6 — tentative.** Dropping arbitrary port `attrs` is presumed fine;
  revisit when the migrator is written.

### D1 — Wires are hosts

**Accepted.** A wire is a **`host` whose `Thing` is of a “wire”
thing-type**, carrying exactly two interfaces named `"a"` and `"b"`
and no address.

Rationale: in DistKV a `Wire` is structurally a host with two fixed ports
`"a"`/`"b"` that participates in cables exactly like a host port. Folding
wires into the host+interface model lets **every cable endpoint be an
interface**, removing the `Wire` class and all the
`isinstance(cc.host, Wire)` / `other_end` special-casing in
`connected_hosts`, `ports`, and `host_find`. The traversal rule “enter a
host via one interface, leave via any *other* interface of that host”
naturally handles a wire (it has exactly two interfaces). The “A end is
closer to the main router” convention survives as the interface names
`"a"`/`"b"`.

A wire is a physical, labelable, locatable object, so making it a `Thing`
is arguably *more* correct than the DistKV model. Wires carry no `domain`
FQDN (they use their hyphenated name) and no address.

*Alternative (not recommended):* a separate `wire` table also referencing
a `Thing`, owning two interface rows. This forces the `interface` table to
be polymorphic in its owner (`host_id` xor `wire_id`), or a separate
`wire_interface` table, both of which reintroduce the special-casing the
unification removes.

### D2 — Concrete address *and* host number, both stored

**Accepted (modified).** An `interface` stores **both** its concrete
address (`addr` + `prefix`) *and* its host offset **`num`** within the
network. The `shift`/`mac` flags remain **allocation policy on the
`network`**.

Rationale: storing the address directly makes reverse lookup (IP →
interface) a trivial indexed equality/containment query instead of the
DistKV `net.enclosing()` + `net.by_num()` dance. Keeping `num` as a
column serves two purposes the user called out:

(a) the IPv4 (mapped) address is still **derived from `num`** —
    `addr = network.base + (num << network.shift)` — so `num` is the
    authoritative allocator value and the stored `addr` is its
    materialisation (kept in sync by the writer/validator);
(b) **finding a free host address** scans small integer `num` values
    (skipping the DHCP range and network/broadcast positions) rather than
    probing the 16-byte `addr` field — cheaper and clearer.

`num` is **nullable**: it is `NULL` for MAC-mode interfaces (address
derived from the MAC, see Q1), for wire `a`/`b` interfaces (no address),
and for any interface not yet assigned an address. Uniqueness is
`UNIQUE(net_id, num)`; SQL engines treat `NULL` as distinct in a unique
constraint, so multiple un-numbered interfaces on a network are allowed.

See “Address computation” for the MAC-mode caveat.

### D3 — Master/slave (“co-existing”) networks — DEFERRED

*Deferred.* Whether/how slave-network addresses are represented is left
open for now. The `network.master_id` self-FK is **retained** as a
placeholder so the co-existence relationship can be recorded (and
preserved by the migrator) without committing to a materialisation policy
yet. Decide after Q1/Q2 land.

### D4 — Short name lives on `Thing.name` only

**Accepted (modified).** There is **no separate `host.name` column**; the
short name is stored once, on `thing.name`. Thus:

- `host.domain` — the FQDN (e.g. `one.you.example`), `VARCHAR(255)`,
  **unique**. The host’s primary identifier (was the DistKV path key).
- `thing.name` — the **short name** (e.g. `you-one`), subject to
  `Thing.name`’s `String(40)` length and global uniqueness across *all*
  things. `thing.descr` ← `host.desc`; `thing.comment` for free text.

Consequence: a host’s short name shares the global thing-name namespace
(and inherits the 40-char cap). If collisions or length ever bite, revisit
by re-adding a `host.name` column and giving the `Thing` a synthetic slug;
out of scope for now.

### D5 — MAC storage

**Accepted.** Store MAC addresses as a 6-byte `BINARY(6)` (mirroring
DistKV’s `EUI.packed`), exposed in Python as `netaddr.EUI` via a small
custom `TypeDecorator`. (The design only mandates the IPv6 treatment for
*IP* addresses; MACs are separate.) An `INTEGER`-backed 48-bit value would
also work and be sortable; `BINARY(6)` is chosen to preserve byte identity
and avoid endianness questions.

### D6 — Arbitrary port `attrs` are dropped — TENTATIVE

*Tentative — revisit when the migrator is written.* DistKV `HostPort`
carried a free-form `attrs` dict (only `vlan` is actually used). The DB
schema models the known fields (`mac`, `force_vlan`, `vlan_id`, `desc`, …)
as columns; unknown attrs would be **dropped** on migration. Before
finalising, the migrator should scan a real DistKV tree for any `attrs`
actually in use beyond `vlan`; if any matter, add a `JSON` column then.

## SQL data structure

All tables sit on `moat.db.schema.Base` (surrogate `id` PK, lowercase
`__tablename__`). Foreign keys use named constraints (`fk_<table>_<col>`)
following the existing `box`/`thing`/`label` convention.

### Address storage type

A reusable `TypeDecorator`/`composite` pair in `moat/db/inv/ip.py`:

- Columns: `addr BINARY(16)` (`LargeBinary`) and `prefix SMALLINT`
  (0–128, the netmask).
- Python ↔ DB:
  - **DB → Python:** unpack the 16 big-endian bytes into a 128-bit int,
    reconstruct `ipaddress.IPv6Address(int)`. If it lies in
    `::ffff:0:0/96`, extract the embedded IPv4 and return
    `IPv4Interface((ipv4, prefix))`; otherwise
    `IPv6Interface((ipv6, prefix))`.
  - **Python → DB:** accept `IPv4Interface`/`IPv6Interface`/
    `IPv4Network`/`IPv6Network`/`str`. Normalise IPv4 to
    `::ffff:a.b.c.d` (`int = (0xffff << 32) | int(ipv4_address)`), then
    pack the 128-bit int as 16 big-endian bytes and store with `prefix`.
- ORM exposure: use `sqlalchemy.orm.composite()` so each model presents a
  single attribute (`interface.address`, `network.subnet`) that is an
  `IPv4Interface`/`IPv6Interface`/`IPv4Network`/`IPv6Network`, backed by
  the two columns. (A plain two-property accessor is the simpler fallback
  if `composite()` proves awkward for mutations.)

**Backing type — decided (Q5): `BINARY(16)`.** A full IPv6 address is 128
bits and does **not** fit in a 64-bit `BIGINT` on SQLite (`INTEGER` is
8-byte signed, max `2**63−1`) or PostgreSQL (`BIGINT` is 64-bit signed).
The IPv4-mapped form `::ffff:a.b.c.d` is only 48 bits and would fit a
`BIGINT`, but native IPv6 (e.g. `2001:780:107::1`) would not. `BINARY(16)`
supports full IPv6: the converter packs/unpacks the 128-bit value as 16
big-endian bytes, and equality/range comparisons on the byte strings sort
correctly for big-endian encoding. The converter is written against an
abstract column type so a future switch (e.g. to a native `INET` on
PostgreSQL) is a one-line change. Below, `addr` columns are shown as
`BINARY(16)` reflecting this decision.

### Tables

#### `vlan`
| column      | type          | notes                                  |
|-------------|---------------|----------------------------------------|
| `id`        | PK            |                                        |
| `tag`       | INT, UNIQUE   | the 802.1Q VLAN number (was path key)  |
| `name`      | VARCHAR(64), UNIQUE |                                   |
| `desc`      | VARCHAR(200)  | nullable                               |
| `wlan`      | VARCHAR(64)   | nullable, WLAN SSID                    |
| `passwd`    | VARCHAR(128)  | nullable, WLAN password                |

#### `network`
| column        | type                 | notes                                       |
|---------------|----------------------|---------------------------------------------|
| `id`          | PK                   |                                             |
| `name`        | VARCHAR(64), UNIQUE  |                                             |
| `addr`        | BINARY(16)           | subnet base address (IPv6 / v4-mapped)      |
| `prefix`      | SMALLINT             | subnet prefix length                        |
| `desc`        | VARCHAR(200)         | nullable                                    |
| `vlan_id`     | FK → `vlan.id`       | nullable                                    |
| `master_id`   | FK → `network.id`    | nullable; supernet this co-exists with       |
| `shift`       | INT, default 0       | host-number shift (allocation policy)        |
| `mac`         | BOOLEAN nullable     | True=MAC-derived only, False=num-derived, NULL=both |
| `virt`        | BOOLEAN, default 0   | no cable required                           |
| `dhcp_first`  | INT                  | nullable; first host offset in DHCP range   |
| `dhcp_count`  | INT                  | nullable; length of DHCP range              |
| `wlan`        | VARCHAR(64)          | nullable (preserved from DistKV `Network`)  |

Composite attribute `subnet` → `IPv4Network`/`IPv6Network`.

#### `host`
| column      | type                 | notes                                         |
|-------------|----------------------|-----------------------------------------------|
| `id`        | PK                   |                                               |
| `thing_id`  | FK → `thing.id`, UNIQUE, NOT NULL | the Thing this host is            |
| `domain`   | VARCHAR(255), UNIQUE | FQDN; primary identifier                      |
| `loc`       | VARCHAR(200)         | nullable, location                            |

`desc`/`comment` live on the `Thing`; the **short name is `thing.name`**
(D4 — no separate `host.name`). `mac`/`net`/`num` move to the `""`
interface (decisions 1 + D2). `groups` via M2M below.

#### `interface`
Unifies the old `HostPort` and the host’s direct attachment.

| column       | type                          | notes                                     |
|--------------|-------------------------------|-------------------------------------------|
| `id`         | PK                            |                                           |
| `host_id`    | FK → `host.id`, NOT NULL      |                                           |
| `name`       | VARCHAR(64)                   | `""` = former direct attachment; `"."` on CLI maps to `""` |
| `net_id`     | FK → `network.id`             | nullable                                  |
| `num`        | INT                           | nullable; host offset within `net` (allocator key; v4 addr derived from it). NULL for MAC-mode / wire / unassigned |
| `addr`       | BINARY(16)                    | nullable; materialised interface address  |
| `prefix`     | SMALLINT                      | nullable; netmask                         |
| `mac`        | BINARY(6)                     | nullable; → `netaddr.EUI`                  |
| `force_vlan` | BOOLEAN, default 0            |                                           |
| `vlan_id`    | FK → `vlan.id`                | nullable; per-interface VLAN override      |
| `desc`       | VARCHAR(200)                  | nullable                                  |

Constraints: `UNIQUE(host_id, name)` (one `""` per host, one `"a"`/`"b"`
per wire, unique port names per host); `UNIQUE(net_id, num)` (no two
interfaces share a host offset on the same network; `NULL` `num` is
distinct, so un-numbered interfaces coexist). Composite attribute
`address` → `IPv4Interface`/`IPv6Interface`. The writer derives `addr`
from `num` for non-MAC networks and keeps them consistent (validator).

#### `cable`
| column       | type                       | notes                              |
|--------------|----------------------------|------------------------------------|
| `id`         | PK                         |                                    |
| `iface_a_id` | FK → `interface.id`, NOT NULL | one end                          |
| `iface_b_id` | FK → `interface.id`, NOT NULL | other end                        |

Constraints: `CHECK (iface_a_id <> iface_b_id)`; `UNIQUE(iface_a_id)` and
`UNIQUE(iface_b_id)` so each interface is in **at most one** cable (matches
DistKV’s one-cable-per-port invariant). Cables are anonymous link records
(not Things); the DistKV `(server, tock)` key is not preserved.

#### `group` and `host_group`
| table        | columns                                 |
|--------------|-----------------------------------------|
| `group`      | `id` PK; `name` VARCHAR(64) UNIQUE; `desc` VARCHAR(200) nullable |
| `host_group` | `host_id` FK → `host.id`, `group_id` FK → `group.id`, composite PK |

### Seeded thing-types

The migrator (and/or an Alembic data migration) ensures non-abstract
`ThingTyp`s named `host` and `wire` exist (D1 accepted). These are
attached under the existing `ThingTyp` tree per `thingtyp_apply`’s
single-root rule; the migrator must find the root or create one. Recorded
here as a dependency, not a schema object.

### Entity-relationship sketch

```
thing ──1:1── host ──1:N── interface ──N:1── network ──N:1── vlan
                   │            │                  │
                   │            └──N:1── vlan (override)
                   └──N:M── group (via host_group)

network ──N:1── network (master_id, self-ref)

cable ──2:1── interface  (iface_a_id, iface_b_id)
```

## Package & refactoring structure

New package `moat.db.inv`, laid out exactly like `moat.db.box` /
`moat.db.thing`:

```
moat/db/inv/
  __init__.py        # docstring; CfgStore.with_(__name__) if a _cfg.yaml is needed
  ip.py              # the address TypeDecorator / composite + conversion helpers
  model.py           # ORM models: Vlan, Network, Host, Interface, Cable, Group, host_group
  model_.py          # relationship wiring + *.apply() (resolve FKs by name, like box/thing)
  _main.py           # CLI: `mt db inv …` (load_subgroup(prefix="moat.db.inv"))
  _cfg.yaml          # optional; only if static config is required
```

Registration / wiring (all edits to existing files):

- `moat/db/_cfg.yaml` — append to `schemas:`:
  `moat.db.inv.model` and `moat.db.inv.model_` (the latter resolves import
  cycles, as for `box`/`thing`).
- Root `pyproject.toml` — add `"moat/db/inv/"` to `[tool.ty.src.include]`.
- `docs/moat-db/index.md` — add `../moat-db-inv/index` to the toctree.
- `docs/moat-db-inv/{index.md,api.rst}` — new doc stubs (mirror
  `moat-db-thing`); this `MIGRATION.md` lives here too.

Packaging (do during the build/tag step, not part of this plan’s commit):

- `packaging/moat-db-inv/{pyproject.toml,README.md}` mirroring
  `packaging/moat-db-thing/`; depends on `moat-db ~= <ver>`,
  `moat-thing ~= <ver>`, `moat-lib-run ~= <ver>`, plus `netaddr` (new dep
  for `EUI`).
- `versions.yaml` — `mt src tag -s moat.db.inv -m` allocates the entry.

Alembic:

- One new revision under `moat/db/alembic/versions/` creating the seven new
  tables and the thing-type seed. Generate with `mt db mig rev …` after the
  models compile, then hand-edit (the existing revisions are
  autogenerated-then-adjusted, and are excluded from ruff/ty).

Old code:

- `moat/kv/inv/` stays **as the migration source**; deprecate it in its
  README but do not delete yet. `mt kv inv …` continues to work so the old
  data can be exported. Removal is a follow-up after the migration has run.

### ORM conventions to follow

Copy the established `moat.db` patterns exactly:

- Models declare columns/relationships in `model.py`; cross-package
  `relationship()` assignments that would create import cycles go in
  `model_.py` using `cast(Any, Model).rel = relationship(...)` (see
  `moat/db/box/model_.py`).
- Mutable-property application goes through a per-model `apply(**kw)`
  method that resolves names to ORM objects via `sess.one(Table, name=…)`,
  honours `NotGiven` sentinels, and wraps lookups in `sess.no_autoflush`
  (see `box_apply`, `thing_apply`).
- `dump()` on each model returns a `dict` of non-null, non-FK-id columns
  plus resolved names, for `yprint`.
- Validators that need the session (e.g. “interface name unique within
  host”, “cable endpoints distinct and unused”) use SQLAlchemy
  `@event.listens_for(Model, "before_insert"/"before_update")` like
  `validate_thing_coords`, or are enforced by the constraints above.

## CLI surface (`mt db inv …`)

Mirror the DistKV commands, adapted to the new model and the `moat.db` CLI
style (`option_ng`, `sess.one(...)`, `yprint`, like `mt db thing`). Define
the groups inline in `moat/db/inv/_main.py` (as `box`/`thing` do), not as
submodules.

- `mt db inv vlan   {add,set,delete,show}` — `-d/--desc`, `-w/--wlan`,
  `-p/--passwd`; id = the `tag` number.
- `mt db inv net    {add,set,delete,show}` — `-d/--desc`, `-v/--vlan`,
  `-a/--dhcp FIRST LEN`, `-m/-M/-B` (mac/no-mac/both), `-V/-R` (virt/real),
  `-S/--master`, `-s/--shift`; id = the `name` (address shown via `subnet`).
- `mt db inv host   {add,set,delete,show}` — `-d/--desc` (→ `thing.descr`),
  `-l/--loc`, `-N/--name`, `-t/--thingtyp` (defaults to `host`);
  **address options move off the host** onto its interfaces.
- `mt db inv host HOST iface {add,set,delete,show,link}` — manage
  interfaces. `HOST iface .` selects the empty-named interface (former
  direct attachment). Options: `-n/--net`, `-i/--num`, `-a/--alloc`,
  `-m/--mac`, `-v/--vlan`, `--force-vlan`, `-d/--desc`, `-N/--name` (rename).
  `link DEST` replaces the old `port link`/`wire link` and creates a
  `cable` between two interfaces.
- `mt db inv wire {add,set,delete,show,link}` — a wire is a `host` with a
  `wire` thing-type and two interfaces `a`/`b` (D1); this command is a thin
  specialisation of `host`. `link` connects the `a` or `b` interface
  (default `b`) to another wire’s end.
- `mt db inv cable {show,…}` — list/manage cables (mostly listing; link/unlink
  happen via `iface link`).
- `mt db inv group  {add,set,delete,show}` and host↔group membership
  (`mt db inv host HOST group …`).
- `mt db inv migrate-from-kv` — the one-time importer (see below).

Naming: the old term “port” becomes **“interface”** (`iface`), matching
decision 1’s wording.

## Semantic changes to call out

- **Direct attachment → `""` interface.** Anything that read `Host.net` /
  `Host.num` now reads the host’s `""` interface. `Host.netaddr` /
  `Host.netaddrs` become “the addresses of the host’s interfaces”.
- **Reverse lookup (IP → host) simplifies.** `HostRoot.by_name(IP)` did
  `net.enclosing(IP)` then `net.by_num(offset)`. Now: query
  `Interface` by `addr` (exact) or by containment in the interface’s
  `/prefix`, then join to `host`. No `enclosing`/`by_num` needed.
- **`connected_hosts` / `host_find` traversal** becomes a graph walk over
  `interface → cable → interface → (host) → other interfaces of that host`.
  Wires need no special case (D1): a wire is a host with exactly two
  interfaces, so “leave via the other interface” just works.
- **Allocation** (`Network.alloc`) moves to a network method that finds
  the first free **`num`** (scanning small integer `interface.num` values
  on the network, skipping the DHCP range
  `dhcp_first..dhcp_first+dhcp_count-1` and the network/broadcast
  positions, applying `shift`) and then materialises `addr = base +
  (num << shift)` via the `ip.py` converter (D2). Scanning `num` is cheaper
  and clearer than probing the 16-byte `addr`. MAC-mode networks derive
  the address from the interface MAC instead (formula to be confirmed —
  Q1).
- **`host_template` / `connected_vlans`** are ported later (out of scope
  here) but depend only on the interface/cable/vlan graph, which the new
  schema represents directly.

## Data migration

A one-time importer `mt db inv migrate-from-kv` (or a script under
`examples/moat-db-inv/`) that reads the live DistKV tree via the existing
`moat.kv.inv.model.InventoryRoot.as_handler(client)` and writes the new
rows in one DB transaction.

### Source → target mapping

| DistKV                                          | Target                                                                 |
|-------------------------------------------------|------------------------------------------------------------------------|
| `InventoryRoot.vlan[*]`                          | `vlan` (`tag`=path key, `name`, `desc`, `wlan`, `passwd`)              |
| `InventoryRoot.net[*]` (`Network`)               | `network` (`addr`+`prefix` from `net.net`, `name`, `desc`, `vlan_id` by name, `master_id` by name, `shift`, `mac`, `virt`, `dhcp_first/count`, `wlan`) |
| `InventoryRoot.group[*]`                         | `group` (`name`)                                                       |
| `InventoryRoot.host[*]` (`Host`)                 | `Thing` (`name`=short, `descr`=`desc`, `thingtyp`=`host`) + `host` (`domain`=FQDN, `loc`) |
| `Host.net`+`Host.num` (direct)                   | `interface` (`host_id`, `name=""`, `net_id`, `num`, `addr`+`prefix` materialised from `num`, `mac`←`Host.mac`) |
| `Host.port[name]` (`HostPort`)                   | `interface` (`host_id`, `name`, `net_id`, `num`, `addr`+`prefix`, `mac`, `force_vlan`, `vlan_id` by name, `desc`) |
| `InventoryRoot.wire[*]` (`Wire`)                 | (D1) `Thing` (`name`=wire name, `thingtyp`=`wire`) + `host` (`domain`=wire name, `loc`, `desc`) + two `interface` `a`/`b` (no address, `num`=NULL) |
| `InventoryRoot.cable[*]` (`Cable.dest_a/dest_b`) | `cable` (`iface_a_id`, `iface_b_id` resolved from the endpoint’s host+port-name; host-direct endpoint → `""` interface; wire endpoint → `a`/`b`) |
| `Host.groups`                                   | `host_group` rows (resolve group names)                                |

### Ordering

1. Seed `ThingTyp` `host` (and `wire`).
2. `vlan` rows.
3. `network` rows — insert with `master_id = NULL` first, then a second pass
   setting `master_id` (masters may forward-reference each other).
4. `group` rows.
5. `Thing` + `host` rows (all hosts and wires).
6. `interface` rows — host-direct `""`, each named port, and wire `a`/`b`.
   Compute addresses here (see below).
7. `cable` rows — resolve both endpoints to `interface.id`.
8. `host_group` associations.

### Address computation

Each interface carries its `num` (copied straight from DistKV’s
`Host.num` / `HostPort.num`) **and** a materialised `addr`+`prefix`:

- Non-MAC network: `addr = network.base + (num << network.shift)`,
  `prefix = network.prefix`, where `base` is the IPv6-normalised network
  base (IPv4 nets stored as `::ffff:a.b.c.d`). Reproduces
  `Network.addr(num)`. Both `num` and `addr` are written to the row.
- MAC-mode network (`network.mac is True`): `num` is `NULL`; the address
  is derived from the interface MAC. **The DistKV `addr()` path is not
  callable in MAC mode** (`num << -1` raises), so DistKV never actually
  stored/computed a MAC-mode address — it was derived ad hoc (e.g. the
  manual IPv6 in `host_template`). The exact formula must be supplied by
  the maintainer (Q1); until then the migrator leaves MAC-mode interface
  addresses `NULL` and logs a warning.
- Master/slave co-existence (D3, **deferred**): the migrator records
  `network.master_id` but does **not** materialise slave-network interface
  rows yet. Decide the policy together with Q2.

Store every computed address via the `ip.py` converter so IPv4 is
normalised to `::ffff:a.b.c.d` (packed into `BINARY(16)`).

### Edge cases / risks

- **Idempotency:** the importer is *not* idempotent. Guard with a check
  (e.g. refuse if `host`/`vlan` rows already exist) or require `--force`.
- **Name collisions:** `Thing.name` (the short name, D4) must be globally
  unique among things and ≤40 chars. The importer detects collisions and
  either renames or aborts with a report.
- **Dangling cables:** a DistKV cable whose endpoint host/port no longer
  exists is skipped and logged (DistKV tolerates these via `_resolve`
  returning `None`).
- **Duplicate names:** DistKV `Network`/`Vlan` enforce unique names at
  `save()` time; the importer trusts this but verifies against the DB’s
  UNIQUE constraints and reports failures.
- **`master` cycles / chains:** `Network._add_slave` guards against
  cycles; the importer should too (`network.master_id` must not form a
  cycle).
- **Big (>64-bit) network numbers:** DistKV stored `>2**64` netnums as
  16-byte blobs (IPv6). The importer reads `Network.net` (`IPNetwork`)
  directly, so this is handled transparently — no special-casing needed.
- **Ordering of `set_value` side effects:** DistKV rebuilt cross-references
  (`_add_host`, `_add_slave`, `_add_net`) reactively. The importer builds
  them imperatively in the ordering above, so it does not depend on
  DistKV’s reactive bookkeeping.

## Open questions

1. **MAC-mode address formula.** What is the intended derivation of an
   IPv6 address from a host MAC for `network.mac is True`? (DistKV never
   implemented it coherently.) Needed for both migration and runtime
   allocation.
2. **Master/slave (co-existence) materialisation — deferred with D3.**
   Should a host on a master net get mirrored interface rows on each slave
   net, and should assigning on a master auto-create/update the slave
   interfaces or be manual? Decide after Q1.
3. ~~**Wires-as-hosts (D1).**~~ **Resolved — accepted:** wires are
   `host`+`Thing` of type `wire`.
4. ~~**`Thing.name` scope (D4).**~~ **Resolved — accepted:** no separate
   `host.name`; the short name lives on `thing.name` (revisit only if
   collisions/length bite).
5. ~~**`addr` backing type.**~~ **Resolved — accepted:** `BINARY(16)`
   (full IPv6), packed big-endian.
6. **Removal of `moat/kv/inv`.** Schedule the follow-up that deletes the
   DistKV inventory package after the migration has run everywhere.
7. **Arbitrary port `attrs` (D6, tentative).** At migrator-writing time,
   scan a real DistKV tree for `attrs` in use beyond `vlan`; add a `JSON`
   column if any matter.

## Task breakdown

1. `moat/db/inv/ip.py` — address composite type + converters (`BINARY(16)`
   big-endian pack/unpack; v4-mapping to/from `::ffff:a.b.c.d`; v4/v6
   round-trip unit tests).
2. `moat/db/inv/model.py` + `model_.py` — the seven models, relationships,
   `apply()`/`dump()`, validators.
3. Register in `moat/db/_cfg.yaml`; add to `pyproject.toml` ty includes.
4. `moat/db/inv/_main.py` — CLI groups (`vlan`, `net`, `host`, `iface`,
   `wire`, `cable`, `group`).
5. Alembic revision (autogenerate, then hand-edit) + `ThingTyp` seed.
6. `packaging/moat-db-inv/` + `versions.yaml` entry; `docs/moat-db-inv/`
   stubs + toctree wiring.
7. `mt db inv migrate-from-kv` importer + a test fixture built from a small
   DistKV inventory snapshot.
8. Port `host_find` / `connected_hosts` / `host_template` (follow-up, out
   of scope here).
9. Deprecate, then later remove, `moat/kv/inv` (follow-up).
