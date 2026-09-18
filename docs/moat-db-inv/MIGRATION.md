---
orphan: true
---

# Migration plan: `moat-kv-inv` → `moat.db.inv`

This document plans the move of the network inventory (`mt kv inv …`,
implemented in `moat/kv/inv/`) from DistKV to a relational database, via a
new `moat.db.inv` package built on `moat.db` (SQLAlchemy + Alembic).

It covers the SQL data structure, the package/refactoring work, and the
one-time data migration from DistKV. It is a **plan**: nothing here is
committed code yet. Decisions marked *accepted* are locked; items in
“Open questions” still need confirmation.

## Goal

Replace the DistKV-backed inventory with a database-backed one, preserving
the existing concepts (VLANs, networks, hosts, interfaces/ports, cables,
wires, groups) while adopting the design decisions below.

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
   Every network and interface address is stored as an **address + prefix**
   pair, using the IPv4-mapped IPv6 representation (`::ffff:a.b.c.d`) for
   IPv4. The original wording said “`BIGINT` + `TINYINT`”; a 128-bit IPv6
   value does not fit a 64-bit `BIGINT`, so the address column is realised
   as **`BINARY(16)`** (big-endian) with a `SMALLINT` prefix (see “Address
   storage type”). On the Python side the value is exposed as an
   `ipaddress.IPv4Interface` (for IPv4-mapped addresses) or
   `ipaddress.IPv6Interface` (for native IPv6); networks analogously as
   `IPv4Network` / `IPv6Network`.

   *Structural refinement (this revision):* IP addresses live in their own
   `address` table keyed by interface, not as columns on the interface
   (see “Network and address data structure”).

## Network and address data structure

The model separates **L2** (a VLAN, the broadcast domain an interface is
plugged into) from **L3** (the IP addresses carried on that VLAN):

* **VLANs.** A `vlan` row (802.1Q tag, name, WLAN creds).

* **Networks live on a VLAN.** Zero or more `network` rows per VLAN —
  typically two, one IPv4 and one IPv6. A network has a **network address**
  (host bits zeroed) and a **netmask** (`prefix`). `network.shift`, when
  **not null**, says how to autogenerate an interface’s address on this
  network from its sequence number:
  `addr = network.addr + (seqnum << network.shift)`.

* **Interfaces attach to a VLAN.** An `interface` belongs to a host
  (`UNIQUE(host_id, ifname)`) and carries an `fk(vlan)`, a **MAC**, and a
  **sequence number** (`seqnum`). `UNIQUE(vlan_id, seqnum)` is enforced
  (see below for why this realises the requested `unique(network,
  seqnum)`).

* **Addresses are a separate table.** Zero or more `address` rows per
  interface: `fk(interface)`, `unique(ipaddr)`. An address **may or may
  not** be derived from `network.addr + (seqnum << network.shift)`, so it
  is stored explicitly. The address record does **not** refer to the
  network it is in: (a) the network can be recovered by containment lookup
  when needed; (b) anycast / singlecast routing requires permitting
  addresses that are not confined to a single network, or even a single
  VLAN. This is the L2/L3 split: the interface’s `vlan_id` is layer-2
  connectivity; an `address` is layer-3 and may roam.

### How addresses are derived

* **Routed networks (IPv4 or IPv6): seqnum.** For a network with
  `shift` not null, an interface on that network’s VLAN gets
  `addr = network.addr + (seqnum << network.shift)`. One such address row
  is produced per routable network in the VLAN, all from the single shared
  `seqnum`.
* **Link-local (`fe80::/10`): MAC (EUI-64), computed, not stored.** An
  interface’s link-local address is derived from its MAC by the EUI-64
  procedure (flip the U/L bit of the first MAC octet, insert `ff:fe`,
  prepend `fe80::`), i.e. `netaddr.EUI.ipv6_link_local()`. Because the MAC
  is already unique per interface, this address is fully determined by the
  interface and is **never stored** as an `address` row — it is exposed as a
  computed property of the interface. The `address` table actively
  **rejects** 48-bit-MAC-derived `fe80::` inserts (see the `address`
  validator) so no redundant/duplicate row can be created.
* **Manual / anycast:** any other `address` row, not matching a derivation,
  stored directly. This covers routed/anycast addresses that sit on an
  interface but belong to a network outside the interface’s VLAN.

### Why `UNIQUE(vlan_id, seqnum)` ≡ `unique(network, seqnum)`

An interface has exactly one `seqnum` (shared across all the VLAN’s
networks) and exactly one `vlan_id`. Each `network` belongs to exactly one
VLAN (`network.vlan_id` is `NOT NULL`). Therefore two interfaces claiming
the same `seqnum` on the same VLAN would collide on every routable network
of that VLAN; two interfaces on different VLANs never share a network. So
`UNIQUE(vlan_id, seqnum)` (with `seqnum NOT NULL` via a partial index, or
relying on standard NULL-distinct semantics for un-numbered interfaces) is
the physical enforcement of the requested `unique(network, seqnum)`.

## Glossary: old term → new term

| DistKV (`moat/kv/inv`)         | `moat.db.inv`                                   |
|--------------------------------|-------------------------------------------------|
| `Vlan`                         | `vlan` row                                      |
| `Network`                      | `network` row (on a VLAN)                       |
| `Host`                         | `thing` + `host` row                            |
| `Host.net` / `Host.num`        | `interface` (seqnum) + `address` rows           |
| `HostPort`                     | `interface` (seqnum) + `address` rows           |
| host address                   | `address` row                                    |
| `Wire`                         | *(see D1)*                                       |
| `Cable`                        | `cable` row                                     |
| group (named)                  | `group` row + `host_group` M2M                  |
| `Host.mac`                     | `mac` on the `""` interface                     |
| path key `(bits, netnum)` net  | `network.addr` + `network.prefix`               |
| path key `(server, tock)` cable| `cable.id` (surrogate)                          |

## Derived decisions

Status as of this revision:

- **D1 — accepted.** Wires are hosts (Thing type `wire`).
- **D2 — revised.** The interface stores `seqnum`; IP addresses live in a
  separate `address` table (no `addr`/`prefix` on the interface).
- **D3 — resolved (subsumed).** IPv4/IPv6 co-existence is now “two networks
  on one VLAN”; an interface auto-gets addresses on all its VLAN’s routable
  networks. `network.master_id` is dropped.
- **D4 — accepted (modified).** No separate `host.name`; the short name
  lives on `thing.name`.
- **D5 — accepted.** MAC as `BINARY(6)` → `netaddr.EUI`.
- **D6 — tentative.** Dropping arbitrary port `attrs` is presumed fine;
  revisit when the migrator is written.
- **Q1 — resolved.** Link-local = EUI-64 from MAC; routed = seqnum.

### D1 — Wires are hosts

**Accepted.** A wire is a **`host` whose `Thing` is of a “wire”
thing-type**, carrying exactly two interfaces named `"a"` and `"b"`, with
no VLAN, no MAC, no `seqnum`, and no addresses. Folding wires into the
host+interface model lets **every cable endpoint be an interface**,
removing the `Wire` class and all the `isinstance(cc.host, Wire)` /
`other_end` special-casing in `connected_hosts`, `ports`, and `host_find`.
The traversal rule “enter a host via one interface, leave via any *other*
interface of that host” naturally handles a wire (exactly two interfaces);
the “A end is closer to the main router” convention survives as the
interface names `"a"`/`"b"`.

### D2 — `seqnum` on the interface; addresses in their own table

**Revised.** An `interface` stores its **`seqnum`** (the host offset within
the VLAN) but **not** its IP address. IP addresses are rows of a separate
`address` table (`fk(interface)`, `unique(ipaddr)`).

Rationale: the interface is an L2 object (plugged into a VLAN, has a MAC,
has a sequence number). Its addresses are L3 and there can be several (one
per routable network in the VLAN, plus link-local, plus any manual/anycast
addresses). Keeping `seqnum` on the interface serves the two purposes the
user called out: (a) the routable address is still **derived from `seqnum`**
(`addr = network.addr + (seqnum << network.shift)`); (b) **finding a free
address** scans small integer `seqnum` values per VLAN (skipping the DHCP
range) rather than probing the 16-byte `addr` field — cheaper and clearer.
`seqnum` is **nullable** (`NULL` for wires, for MAC-only/link-local
interfaces, and for not-yet-numbered interfaces).

### D3 — IPv4/IPv6 co-existence: RESOLVED (subsumed)

**Resolved.** The old master/slave machinery existed to give a host both an
IPv4 and an IPv6 address. In the new model a VLAN simply carries **two (or
more) networks** — typically IPv4 and IPv6 — and an interface on that VLAN
automatically receives a derived address on **each** routable network from
its single `seqnum` (plus a link-local address from its MAC). Co-existence
is therefore intrinsic; no `master_id`, no slave materialisation, no
special-case code. `network.master_id` is **dropped**.

### D4 — Short name lives on `Thing.name` only

**Accepted (modified).** No separate `host.name` column; the short name is
stored once, on `thing.name` (subject to `Thing.name`’s `String(40)`
length and global uniqueness across all things). `host.domain` is the
FQDN (`VARCHAR(255)`, unique) and the host’s primary identifier. If
collisions or length ever bite, revisit by re-adding `host.name` and giving
the `Thing` a synthetic slug.

### D5 — MAC storage

**Accepted.** MAC addresses are a 6-byte `BINARY(6)` (mirroring DistKV’s
`EUI.packed`), exposed in Python as `netaddr.EUI` via a small custom
`TypeDecorator`. `netaddr.EUI` also provides `.ipv6_link_local()` used for
the link-local derivation (Q1).

### D6 — Arbitrary port `attrs` dropped — TENTATIVE

*Tentative — revisit when the migrator is written.* DistKV `HostPort`
carried a free-form `attrs` dict (only `vlan` is actually used). The DB
schema models the known fields as columns; unknown attrs would be dropped
on migration. Before finalising, the migrator should scan a real DistKV
tree for any `attrs` in use beyond `vlan`; if any matter, add a `JSON`
column then.

## SQL data structure

All tables sit on `moat.db.schema.Base` (surrogate `id` PK, lowercase
`__tablename__`). Foreign keys use named constraints (`fk_<table>_<col>`)
following the existing `box`/`thing`/`label` convention.

### Address storage type

A reusable `TypeDecorator`/`composite` pair in `moat/db/inv/ip.py`:

- Columns: `addr BINARY(16)` (`LargeBinary`) and `prefix SMALLINT`
  (0–128, the netmask; nullable on `address`).
- Python ↔ DB:
  - **DB → Python:** unpack the 16 big-endian bytes into a 128-bit int,
    reconstruct `ipaddress.IPv6Address(int)`. If it lies in
    `::ffff:0:0/96`, extract the embedded IPv4 and return
    `IPv4Interface((ipv4, prefix))` (or a bare `IPv4Address` when `prefix`
    is null); otherwise `IPv6Interface((ipv6, prefix))` (or bare
    `IPv6Address`).
  - **Python → DB:** accept `IPv4Interface`/`IPv6Interface`/
    `IPv4Network`/`IPv6Network`/`str`. Normalise IPv4 to
    `::ffff:a.b.c.d` (`int = (0xffff << 32) | int(ipv4_address)`), then
    pack the 128-bit int as 16 big-endian bytes and store with `prefix`.
- ORM exposure: `sqlalchemy.orm.composite()` on the `address` and `network`
  tables presents a single attribute (`address.ip`, `network.subnet`).

**Backing type — decided (Q5): `BINARY(16)`.** A 128-bit IPv6 address does
not fit a 64-bit `BIGINT` on SQLite or PostgreSQL; `BINARY(16)` supports
full IPv6, packed big-endian so byte-string comparisons sort correctly. The
converter is written against an abstract column type so a future switch
(e.g. native `INET` on PostgreSQL) is a one-line change.

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
A network lives on exactly one VLAN; a VLAN carries zero or more networks
(typically IPv4 + IPv6).

| column        | type                 | notes                                            |
|---------------|----------------------|--------------------------------------------------|
| `id`          | PK                   |                                                  |
| `name`        | VARCHAR(64), UNIQUE  |                                                  |
| `vlan_id`     | FK → `vlan.id`, NOT NULL | the VLAN this network rides on              |
| `addr`        | BINARY(16)           | network address (host bits zeroed; IPv6 / v4-mapped) |
| `prefix`      | SMALLINT             | netmask                                          |
| `shift`       | INT, nullable        | if set, autogen `addr = net.addr + (seqnum<<shift)`; null = no seqnum autogen |
| `desc`        | VARCHAR(200)         | nullable                                         |
| `virt`        | BOOLEAN, default 0   | no cable required                                |
| `dhcp_first`  | INT                  | nullable; first `seqnum` in the DHCP range        |
| `dhcp_count`  | INT                  | nullable; length of the DHCP range               |

Composite attribute `subnet` → `IPv4Network`/`IPv6Network`.

Notes:
- `network.mac` (the old tri-state) is **gone**. A `network` row’s
  derivation mode is now simply: `shift` not null → seqnum autogen
  (`addr = net.addr + (seqnum << shift)`); `shift` null → no autogen
  (manual addresses only). Link-local `fe80::` addresses are not a
  network concern at all — they are computed from each interface’s MAC
  (Q10) and never stored, so there is no link-local `network` row and no
  prefix-based detection to worry about.
- `network.master_id` and `network.wlan` are **dropped** (D3; WLAN creds
  live on the `vlan`).

#### `host`
| column      | type                 | notes                                         |
|-------------|----------------------|-----------------------------------------------|
| `id`        | PK                   |                                               |
| `thing_id`  | FK → `thing.id`, UNIQUE, NOT NULL | the Thing this host is            |
| `domain`   | VARCHAR(255), UNIQUE | FQDN; primary identifier                      |
| `loc`       | VARCHAR(200)         | nullable, location                            |

`desc`/`comment` live on the `Thing`; the **short name is `thing.name`**
(D4 — no separate `host.name`). The host’s MAC, VLAN attachment (`seqnum`),
and IP addresses live on its `""` interface and that interface’s
`address` rows (decisions 1 + D2). `groups` via M2M below.

#### `interface`
Belongs to a host (named) and is plugged into a VLAN. Unifies the old
`HostPort` and the host’s direct attachment.

| column       | type                          | notes                                     |
|--------------|-------------------------------|-------------------------------------------|
| `id`         | PK                            |                                           |
| `host_id`    | FK → `host.id`, NOT NULL      |                                           |
| `name`       | VARCHAR(64)                   | `""` = former direct attachment; `"."` on CLI maps to `""` |
| `vlan_id`    | FK → `vlan.id`                | nullable; the VLAN this interface is on (NULL for wire `a`/`b`) |
| `mac`        | BINARY(6)                     | nullable; → `netaddr.EUI`                  |
| `seqnum`     | INT                           | nullable; host offset within the VLAN (allocator key; routable addr derived from it). NULL for wires / link-local-only / unassigned |
| `desc`       | VARCHAR(200)                  | nullable                                  |

Constraints:
- `UNIQUE(host_id, name)` — one `""` per host, one `"a"`/`"b"` per wire,
  unique interface names per host.
- `UNIQUE(vlan_id, seqnum)` — realises `unique(network, seqnum)` (see the
  rationale above). Standard SQL treats `NULL` as distinct in a unique
  constraint, so multiple un-numbered interfaces coexist; alternatively a
  partial unique index `WHERE seqnum IS NOT NULL`.

The interface holds **no IP columns**; its addresses are `address` rows.
Trunk / multi-VLAN ports are out of scope (one interface = one VLAN); the
old per-port `force_vlan`/`vlan_id` override is therefore dropped.

#### `address`
Zero or more per interface. The L3 layer.

| column        | type                          | notes                                     |
|--------------|-------------------------------|-------------------------------------------|
| `id`         | PK                            |                                           |
| `interface_id` | FK → `interface.id`, NOT NULL |                                           |
| `addr`       | BINARY(16)                    | the IP address (IPv6 / v4-mapped)         |
| `prefix`     | SMALLINT                      | nullable; netmask. Equals the containing network’s prefix when the address is in one; NULL for floating/anycast addresses with no network |

Constraint: `UNIQUE(addr)` — an IP is assigned to one interface
(`unique(ipaddr)`). The record deliberately has **no `network_id`**: the
network is recoverable by containment lookup (point a), and anycast routing
needs addresses not pinned to a network/VLAN (point b). Strict anycast
(the *same* IP on multiple interfaces) would require relaxing this
constraint — flagged as a possible future need, not supported now.

Validator (Q10): the `address` table **rejects** 48-bit-MAC-derived
link-local addresses — any `fe80::/10` address whose interface identifier
is an EUI-64 formed from a 48-bit MAC (detectable structurally: the
`ff:fe` infix between the two MAC halves, with the U/L bit flipped). Such
addresses are fully derivable from the interface’s already-unique `mac`
(exposed as a computed property), so storing them is redundant and would
duplicate/shadow the computed value. Manual non-EUI-64 `fe80::` addresses
are still allowed. Implemented as a `before_insert`/`before_update`
listener using the `ip.is_mac_link_local()` helper.

Composite attribute `ip` → `IPv4Interface`/`IPv6Interface` (or a bare
`IPv4Address`/`IPv6Address` when `prefix` is null).

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
thing ──1:1── host ──1:N── interface ──N:1── vlan ──1:N── network
                   │            │
                   │            └──1:N── address   (L3; no network FK)
                   └──N:M── group (via host_group)

cable ──2:1── interface  (iface_a_id, iface_b_id)
```

Note the L2/L3 split: `interface → vlan → network` is layer 2; `address`
hangs off `interface` and may belong to any network (or none).

## Package & refactoring structure

New package `moat.db.inv`, laid out exactly like `moat.db.box` /
`moat.db.thing`:

```
moat/db/inv/
  __init__.py        # docstring; CfgStore.with_(__name__) if a _cfg.yaml is needed
  ip.py              # address TypeDecorator / composite + conversion + EUI-64 link-local helper
  model.py           # ORM models: Vlan, Network, Host, Interface, Address, Cable, HostGroup, host_group
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
  for `EUI` and `.ipv6_link_local()`).
- `versions.yaml` — `mt src tag -s moat.db.inv -m` allocates the entry.

Alembic:

- One new revision under `moat/db/alembic/versions/` creating the eight new
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
  host”, “`UNIQUE(vlan_id, seqnum)`”, “cable endpoints distinct and
  unused”) use SQLAlchemy `@event.listens_for(Model,
  "before_insert"/"before_update")` like `validate_thing_coords`, or are
  enforced by the constraints above.
- **Address regeneration:** the interface writer regenerates derived
  `address` rows whenever `seqnum` or the VLAN’s networks change — one
  routable address per VLAN network with `shift` not null from `seqnum` —
  and leaves manual/anycast `address` rows untouched (recognised by not
  matching any derivation). Link-local addresses are **not** regenerated
  or stored: the interface exposes `link_local` as a computed property
  (`mac.ipv6_link_local()` when `mac` is set). The `address` validator
  (above) prevents a MAC-derived `fe80::` row from ever being inserted.

## CLI surface (`mt db inv …`)

Mirror the DistKV commands, adapted to the new model and the `moat.db` CLI
style (`option_ng`, `sess.one(...)`, `yprint`, like `mt db thing`). Define
the groups inline in `moat/db/inv/_main.py` (as `box`/`thing` do), not as
submodules.

- `mt db inv vlan   {add,set,delete,show}` — `-d/--desc`, `-w/--wlan`,
  `-p/--passwd`; id = the `tag` number.
- `mt db inv net    {add,set,delete,show}` — `-v/--vlan` (required on
  `add`), `-s/--shift` (nullable), `-d/--desc`, `-a/--dhcp FIRST LEN`,
  `-V/-R` (virt/real); id = the `name` (address shown via `subnet`).
- `mt db inv host   {add,set,delete,show}` — `-d/--desc` (→ `thing.descr`),
  `-l/--loc`, `-N/--name`, `-t/--thingtyp` (defaults to `host`).
- `mt db inv host HOST iface {add,set,delete,show,link}` — manage
  interfaces. `HOST iface .` selects the empty-named interface (former
  direct attachment). Options: `-V/--vlan` (the VLAN it’s on), `-m/--mac`,
  `-s/--seqnum`, `-a/--alloc` (pick a free `seqnum` on the VLAN), `-d/--desc`,
  `-N/--name` (rename). `link DEST` replaces the old `port link`/`wire
  link` and creates a `cable` between two interfaces.
- `mt db inv host HOST iface IFACE addr {add,delete,show}` — manage the
  interface’s `address` rows (manual/anycast addresses; derived ones are
  regenerated automatically and shown read-only). Options: `-a/--addr`,
  `-p/--prefix`.
- `mt db inv wire {add,set,delete,show,link}` — a wire is a `host` with a
  `wire` thing-type and two interfaces `a`/`b` (D1); a thin specialisation
  of `host`. `link` connects the `a` or `b` interface (default `b`) to
  another wire’s end.
- `mt db inv cable {show,…}` — list/manage cables (mostly listing; link/unlink
  happen via `iface link`).
- `mt db inv group  {add,set,delete,show}` and host↔group membership
  (`mt db inv host HOST group …`).
- `mt db inv migrate-from-kv` — the one-time importer (see below).

Naming: the old term “port” becomes **“interface”** (`iface`), matching
decision 1’s wording.

## Semantic changes to call out

- **Direct attachment → `""` interface.** Anything that read `Host.net` /
  `Host.num` now reads the host’s `""` interface (`seqnum`) and its
  `address` rows. `Host.netaddr` / `Host.netaddrs` become “the `address`
  rows of the host’s interfaces”.
- **Reverse lookup (IP → host) simplifies.** `HostRoot.by_name(IP)` did
  `net.enclosing(IP)` then `net.by_num(offset)`. Now: query `address` by
  `addr` (exact equality on the indexed `BINARY(16)`), join to `interface`
  → `host`. Containment (`addr` within a `network.subnet`) is only needed
  when you specifically want the network, not the host. **Link-local
  `fe80::` addresses are not in the `address` table** (Q10); reverse lookup
  by a link-local IP instead computes each interface’s
  `mac.ipv6_link_local()` and matches (scope-ID disambiguation is the
  caller’s job).
- **IPv4/IPv6 co-existence is automatic (D3).** Putting two networks on one
  VLAN is all it takes; an interface gets a derived address on each. No
  master/slave code.
- **`connected_hosts` / `host_find` traversal** becomes a graph walk over
  `interface → cable → interface → (host) → other interfaces of that host`.
  Wires need no special case (D1): a wire is a host with exactly two
  interfaces, so “leave via the other interface” just works.
- **Allocation** (`Network.alloc` → a VLAN-scoped helper) finds the first
  free **`seqnum`** on the VLAN (scanning small integer `interface.seqnum`
  values, skipping the DHCP range `dhcp_first..dhcp_first+dhcp_count-1`
  where the VLAN’s networks define one) and then derives the routable
  address(es) from it. Scanning `seqnum` is cheaper and clearer than
  probing the 16-byte `addr`. Link-local addresses come from the MAC, not
  the allocator.
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
| `InventoryRoot.net[*]` (`Network`)               | `network` (`name`, `vlan_id` by the net’s VLAN, `addr`+`prefix` from `net.net`, `shift`, `desc`, `virt`, `dhcp_first/count`). Drop `mac`/`master_id`/`wlan`. |
| `InventoryRoot.group[*]`                         | `group` (`name`)                                                       |
| `InventoryRoot.host[*]` (`Host`)                 | `Thing` (`name`=short, `descr`=`desc`, `thingtyp`=`host`) + `host` (`domain`=FQDN, `loc`) |
| `Host.net`+`Host.num` (direct)                   | `interface` (`host_id`, `name=""`, `vlan_id`=`Host.net`’s VLAN, `mac`←`Host.mac`, `seqnum`=`Host.num`) + derived `address` rows (see “Address computation”) |
| `Host.port[name]` (`HostPort`)                   | `interface` (`host_id`, `name`, `vlan_id`=port net’s VLAN, `mac`, `seqnum`=`HostPort.num`, `desc`) + derived `address` rows |
| `InventoryRoot.wire[*]` (`Wire`)                 | (D1) `Thing` (`name`=wire name, `thingtyp`=`wire`) + `host` (`domain`=wire name, `loc`, `desc`) + two `interface` `a`/`b` (no VLAN, no MAC, no `seqnum`, no addresses) |
| `InventoryRoot.cable[*]` (`Cable.dest_a/dest_b`) | `cable` (`iface_a_id`, `iface_b_id` resolved from the endpoint’s host+port-name; host-direct endpoint → `""` interface; wire endpoint → `a`/`b`) |
| `Host.groups`                                   | `host_group` rows (resolve group names)                                |

### Ordering

1. Seed `ThingTyp` `host` and `wire`.
2. `vlan` rows.
3. `network` rows (now a single pass — no `master_id` to defer).
4. `group` rows.
5. `Thing` + `host` rows (all hosts and wires).
6. `interface` rows — host-direct `""`, each named port, and wire `a`/`b`.
7. `address` rows — derived per interface (see below), plus any manual
   addresses carried over from old data.
8. `cable` rows — resolve both endpoints to `interface.id`.
9. `host_group` associations.

### Address computation

For each interface with `seqnum` `S` on VLAN `V` (the MAC `M` is
irrelevant to *stored* addresses — see Q10):

- **Routable networks** (each `network` in `V` with `shift` not null):
  `addr = network.addr + (S << network.shift)`, `prefix = network.prefix`.
  One `address` row per such network. This reproduces DistKV’s
  `Network.addr(num)` for the network that was `Host.net`, and
  additionally materialises the address on every other routable network in
  the VLAN (D3 — co-existence is now automatic).
- **Link-local:** **not migrated.** The link-local `fe80::` address is
  computed from the interface’s MAC at runtime (Q10); no `address` row is
  created. (Old DistKV data never stored one anyway.)
- **MAC-mode caveat:** DistKV’s `addr()` was not callable in MAC mode
  (`num << -1` raises), so DistKV never stored a MAC-mode address — it was
  derived ad hoc. The new model replaces “MAC mode” with the explicit
  link-local EUI-64 rule (runtime-computed, not stored) for the
  link-local part, and ordinary seqnum derivation for the routable part.
  MAC-mode networks in old data that had a `shift` map to ordinary routable
  networks; if an old “MAC-mode” network genuinely had no `shift` and no
  seqnum semantics, its addresses are migrated as manual `address` rows;
  flag any such case for review.

Store every computed address via the `ip.py` converter so IPv4 is
normalised to `::ffff:a.b.c.d` (packed into `BINARY(16)`).

### Behaviour normalisation to review

Because an interface on a VLAN now auto-receives addresses on **all** the
VLAN’s routable networks, a DistKV host that occupied only the IPv4 master
(and had no IPv6 slave address) will gain an IPv6 address after migration
(assuming the VLAN has an IPv6 network with a `shift`). This is the
intended normalisation, but the migrator should **report** the expanded
interfaces so the operator can prune unintended addresses.

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
- **VLAN ambiguity:** an interface is attached to a VLAN, but old DistKV
  attached a host/port to a *network*. The importer derives the VLAN as
  `Host.net.vlan`; if a network had no VLAN in old data, the importer
  reports it and requires a VLAN to be assigned.
- **Big (>64-bit) network numbers:** DistKV stored `>2**64` netnums as
  16-byte blobs (IPv6). The importer reads `Network.net` (`IPNetwork`)
  directly, so this is handled transparently — no special-casing needed.
- **Ordering of `set_value` side effects:** DistKV rebuilt cross-references
  (`_add_host`, `_add_slave`, `_add_net`) reactively. The importer builds
  them imperatively in the ordering above, so it does not depend on
  DistKV’s reactive bookkeeping.

## Open questions

1. ~~**MAC-mode address formula.**~~ **Resolved:** link-local `fe80::/10`
   addresses are EUI-64 from the MAC (`netaddr.EUI.ipv6_link_local()`);
   routed addresses use `seqnum` via `network.shift`.
2. ~~**Master/slave materialisation (D3).**~~ **Resolved (subsumed):** v4
   and v6 are two networks on one VLAN; an interface auto-gets addresses
   on each. `network.master_id` dropped.
3. ~~**Wires-as-hosts (D1).**~~ **Resolved — accepted:** wires are
   `host`+`Thing` of type `wire`.
4. ~~**`Thing.name` scope (D4).**~~ **Resolved — accepted:** no separate
   `host.name`; the short name lives on `thing.name` (revisit only if
   collisions/length bite).
5. ~~**`addr` backing type.**~~ **Resolved — accepted:** `BINARY(16)`
   (full IPv6), packed big-endian.
6. ~~**Removal of `moat/kv/inv`.**~~ **Resolved — scheduled:** filed as a
   separate issue, blocked by this implementation issue (removal proceeds
   once the migration has run everywhere).
7. **Arbitrary port `attrs` (D6, tentative).** Deferred until the
   migrator is written: scan a real DistKV tree for `attrs` in use beyond
   `vlan`; add a `JSON` column if any matter.
8. ~~**`seqnum` scope.**~~ **Resolved — OK:** VLAN-wide (one `seqnum` per
   interface, shared across the VLAN’s networks, enforcing
   `unique(network, seqnum)` via `UNIQUE(vlan_id, seqnum)`). If
   per-network `seqnum` independence is ever needed, switch to an
   `interface_network` junction with `unique(network_id, seqnum)` — out
   of scope now.
9. ~~**Strict anycast.**~~ **Resolved — OK:** `UNIQUE(addr)` forbids the
   same IP on multiple interfaces. If true anycast is needed later, relax
   this (e.g. a flag) — not supported now.
10. ~~**Link-local storage.**~~ **Resolved — not stored:** MAC-derived
    `fe80::` link-local addresses are computed from the interface’s
    already-unique `mac` at runtime (exposed as a computed property), never
    stored as `address` rows. The `address` table rejects 48-bit-MAC-
    derived `fe80::` inserts; manual non-EUI-64 `fe80::` addresses are
    still allowed.

## Task breakdown

1. `moat/db/inv/ip.py` — address composite type + converters (`BINARY(16)`
   big-endian pack/unpack; v4-mapping to/from `::ffff:a.b.c.d`; nullable
   prefix → bare address; EUI-64 link-local helper; `is_mac_link_local()`
   detector for the address-table validator; v4/v6 round-trip unit tests).
2. `moat/db/inv/model.py` + `model_.py` — the eight models (incl.
   `Address`), relationships, `apply()`/`dump()`, validators (including the
   `address` reject-MAC-derived-link-local validator and the
   address-regeneration hook on the interface writer), and the interface’s
   computed `link_local` property.
3. Register in `moat/db/_cfg.yaml`; add to `pyproject.toml` ty includes.
4. `moat/db/inv/_main.py` — CLI groups (`vlan`, `net`, `host`, `iface`,
   `iface addr`, `wire`, `cable`, `group`).
5. Alembic revision (autogenerate, then hand-edit) + `ThingTyp` seed.
6. `packaging/moat-db-inv/` + `versions.yaml` entry; `docs/moat-db-inv/`
   stubs + toctree wiring.
7. `mt db inv migrate-from-kv` importer + a test fixture built from a small
   DistKV inventory snapshot; emit the “expanded interfaces” review
   report.
8. Port `host_find` / `connected_hosts` / `host_template` (follow-up, out
   of scope here).
9. Deprecate, then later remove, `moat/kv/inv` (follow-up).
