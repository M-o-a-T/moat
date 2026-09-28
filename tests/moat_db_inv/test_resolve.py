"""
Tests for :mod:`moat.db.inv.resolve` — the IP → interface/host resolver.

Covers the six unit-test axes from the issue:

* direct IPv6 hit,
* IPv4-mapped hit (dotquad string and address object collapse to the same
  stored key),
* absent address (genuine miss),
* MAC-derivable EUI-64 link-local recognised in best-effort mode and missed
  in strict mode,
* dual-stack duplication collapsing sensibly (both stacks of one interface
  resolve to the same owner),
* anycast double-membership returned pairwise rather than crashing.

The realistic axes run against a database populated by ``mt db inv
migrate-from-kv`` using the existing fixture, so the resolver is exercised
against the real population path. The anycast axis relaxes the
``UNIQUE(addr)`` constraint on a throwaway in-memory schema so a genuine
duplicate-row scenario can be created.
"""

from __future__ import annotations

import ipaddress
import pytest
from pathlib import Path

from sqlalchemy import UniqueConstraint, create_engine, select
from sqlalchemy.orm import Session

import moat.db.inv.model_  # noqa: F401  — wires the Thing relationships
import moat.db.util  # noqa: F401  — sqlite foreign_keys pragma
from moat.db.inv.ip import IpValue, link_local_from_mac
from moat.db.inv.model import Address, Host, Interface
from moat.db.inv.resolve import (
    AddressNotFound,
    AmbiguousAddress,
    resolve_hosts,
    resolve_interfaces,
    resolve_one,
)
from moat.src.test import run

DUMP = Path(__file__).parent / "data" / "kv_inv.yaml"


# ---------------------------------------------------------------------------
# Populated-DB fixture (realistic axes)
# ---------------------------------------------------------------------------


@pytest.fixture
async def db_url(tmp_path):
    "an empty database with the full schema, stamped to head"
    url = f"sqlite:///{tmp_path / 'inv.db'}"
    await run("-s", "moat.db.url", url, "db", "init")
    return url


async def _migrate(url):
    "populate the database from the small DistKV inventory fixture"
    return await run("-s", "moat.db.url", url, "db", "inv", "migrate-from-kv", "-i", str(DUMP))


@pytest.fixture
async def populated_url(db_url):
    "a database initialised and populated by the migrator"
    await _migrate(db_url)
    return db_url


def _session(url):
    """A bare :class:`Session` on the populated file DB.

    The resolver ducks the session (it only needs ``execute``/``scalars``),
    so a plain ``Session`` works just as well as the CLI's :class:`Mgr`.
    Closing the engine is the caller's responsibility.
    """
    eng = create_engine(url)
    sess = Session(eng)
    return sess, eng


# Anchors derived from tests/moat_db_inv/data/kv_inv.yaml (see test_migrate.py):
#   srv.lan.example:en0  MAC 02:00:00:00:00:01, seqnum 10
#     addrs 192.168.1.10/24 and 2001:db8:0:1::a/64
SRV_V4 = ipaddress.ip_address("192.168.1.10")
SRV_V6 = ipaddress.ip_address("2001:db8:0:1::a")
SRV_DOMAIN = "srv.lan.example"
SRV_IFACE = "en0"
SRV_MAC_LL = ipaddress.IPv6Address("fe80::ff:fe00:1")  # link_local_from_mac(02:00:00:00:00:01)


# ---------------------------------------------------------------------------
# Realistic axes against the migrated DB
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_direct_v6_hit(populated_url):
    "a native IPv6 address resolves to its owning interface and host."
    sess, eng = _session(populated_url)
    try:
        ifaces = resolve_interfaces(sess, SRV_V6)
        assert len(ifaces) == 1
        iface = next(iter(ifaces))
        assert iface.name == SRV_IFACE
        assert iface.host.domain == SRV_DOMAIN
        assert iface.host.thing.name == "srv"

        # resolve_one returns the sole interface.
        assert resolve_one(sess, SRV_V6) is iface

        # resolve_hosts collapses to the single owning host.
        hosts = resolve_hosts(sess, SRV_V6)
        assert {h.domain for h in hosts} == {SRV_DOMAIN}
    finally:
        sess.close()
        eng.dispose()


@pytest.mark.anyio
async def test_v4_mapped_hit_and_normalization(populated_url):
    "dotquad string, IPv4Address, and the mapped IPv6 form all hit the same row."
    sess, eng = _session(populated_url)
    try:
        # Spellings of the same address that all collapse to one stored key.
        # A bare int is taken as an already-mapped 128-bit value (per
        # IpValue.from_ip), so the v4-mapped int encodes 192.168.1.10 as
        # (0xffff << 32) | int(addr).
        mapped_int = (0xFFFF << 32) | int(SRV_V4)
        spellings = [
            "192.168.1.10",
            SRV_V4,
            "::ffff:192.168.1.10",
            ipaddress.IPv6Address("::ffff:c0a8:10a"),
            mapped_int,
            IpValue.from_ip(SRV_V4).addr,  # 16 raw bytes
        ]
        baseline = resolve_interfaces(sess, "192.168.1.10")
        assert len(baseline) == 1
        for sp in spellings:
            got = resolve_interfaces(sess, sp)
            assert got == baseline, sp
        iface = next(iter(baseline))
        assert iface.name == SRV_IFACE
        assert iface.host.domain == SRV_DOMAIN
    finally:
        sess.close()
        eng.dispose()


@pytest.mark.anyio
async def test_absent_address(populated_url):
    "an address that is neither stored nor MAC-derivable yields an empty set."
    sess, eng = _session(populated_url)
    try:
        # Routable but unallocated.
        assert resolve_interfaces(sess, "10.255.255.1") == set()
        assert resolve_hosts(sess, "10.255.255.1") == set()
        # Native v6 nothing-there.
        assert resolve_interfaces(sess, "2001:db8:dead:beef::1") == set()
        # strict mode agrees.
        assert resolve_interfaces(sess, "10.255.255.1", strict=True) == set()
        # resolve_one raises AddressNotFound.
        with pytest.raises(AddressNotFound):
            resolve_one(sess, "10.255.255.1")
    finally:
        sess.close()
        eng.dispose()


@pytest.mark.anyio
async def test_unparseable_raises(populated_url):
    "garbage that is not an address surfaces the parser's ValueError."
    sess, eng = _session(populated_url)
    try:
        with pytest.raises(ValueError, match="IPv4 or IPv6"):
            resolve_interfaces(sess, "not.an.address.foo")
    finally:
        sess.close()
        eng.dispose()


@pytest.mark.anyio
async def test_mac_link_local_best_effort_vs_strict(populated_url):
    "a MAC-derived link-local is derivable in best-effort, a miss in strict."
    sess, eng = _session(populated_url)
    try:
        # Sanity: the anchor MAC really derives to the address we assert.
        mac_row = (
            sess.execute(select(Interface).where(Interface.mac.is_not(None))).scalars().first()
        )
        assert mac_row is not None
        ll = link_local_from_mac(mac_row.mac)
        assert ll == SRV_MAC_LL  # the fixture's srv:en0 MAC

        # Best-effort: the address is never stored, but derivation finds it.
        found_be = resolve_interfaces(sess, SRV_MAC_LL, strict=False)
        assert {i.host.domain for i in found_be} == {SRV_DOMAIN}
        assert {i.name for i in found_be} == {SRV_IFACE}

        # Strict: a MAC-derived link-local is a deliberate non-row → miss.
        assert resolve_interfaces(sess, SRV_MAC_LL, strict=True) == set()
        assert resolve_hosts(sess, SRV_MAC_LL, strict=True) == set()
        with pytest.raises(AddressNotFound):
            resolve_one(sess, SRV_MAC_LL, strict=True)

        # A NON-MAC-derived fe80:: (manual) address, by contrast, is a
        # normal stored row in both modes — verified indirectly by confirming
        # the strict branch only short-circuits MAC-derived link-locals.
        # (The fixture has no manual fe80:: row, so we just confirm strict
        # does not mis-classify a random routable address.)
        assert len(resolve_interfaces(sess, SRV_V4, strict=True)) == 1
    finally:
        sess.close()
        eng.dispose()


@pytest.mark.anyio
async def test_dual_stack_collapse(populated_url):
    "both stacks of one interface resolve to the same single owner."
    sess, eng = _session(populated_url)
    try:
        v4_ifaces = resolve_interfaces(sess, SRV_V4)
        v6_ifaces = resolve_interfaces(sess, SRV_V6)
        # Same interface owns both addresses → same single-element set.
        assert v4_ifaces == v6_ifaces
        assert len(v4_ifaces) == 1
        owners = resolve_hosts(sess, SRV_V4) | resolve_hosts(sess, SRV_V6)
        assert {h.domain for h in owners} == {SRV_DOMAIN}
    finally:
        sess.close()
        eng.dispose()


# ---------------------------------------------------------------------------
# Anycast axis — genuine duplicate rows on a throwaway schema
# ---------------------------------------------------------------------------


def _seed_two_hosts_with_same_addr(sess):
    """Insert two hosts whose ``""`` interface shares one address.

    Builds the minimal Thing/ThingTyp/Host/Vlan/Interface/Address graph by
    hand so the test controls exactly which rows exist. Used only on the
    anycast test's private, constraint-relaxed schema.
    """
    from moat.db.thing.model import Thing, ThingTyp  # noqa: PLC0415

    ttyp = ThingTyp(name="host", abstract=False)
    sess.add(ttyp)
    sess.flush()
    t1 = Thing(name="anyc-a", thingtyp=ttyp)
    t2 = Thing(name="anyc-b", thingtyp=ttyp)
    sess.add_all([t1, t2])
    sess.flush()
    h1 = Host(domain="anyc-a.example", thing=t1)
    h2 = Host(domain="anyc-b.example", thing=t2)
    sess.add_all([h1, h2])
    sess.flush()
    i1 = Interface(host=h1, name="")
    i2 = Interface(host=h2, name="")
    sess.add_all([i1, i2])
    sess.flush()

    shared = ipaddress.ip_address("203.0.113.42")
    from moat.db.inv.ip import IpValue  # noqa: PLC0415

    key = IpValue.from_ip(shared).addr
    sess.add(Address(interface=i1, addr=key, prefix=None))
    sess.add(Address(interface=i2, addr=key, prefix=None))
    sess.flush()
    return shared, i1, i2


def test_anycast_double_membership_returned_pairwise():
    "two interfaces sharing one address come back as a pair, not a crash."
    from sqlalchemy import Table  # noqa: PLC0415

    from moat.db.schema import Base  # noqa: PLC0415
    from moat.db.util import load_schemas  # noqa: PLC0415

    from typing import cast  # noqa: PLC0415

    load_schemas()  # ensure all models are imported (FK targets exist)
    tbl = cast(Table, Address.__table__)

    # Relax UNIQUE(addr) on the shared metadata so the throwaway engine's
    # CREATE TABLE omits the constraint. Restored in ``finally`` so the
    # global metadata is left pristine for any later test.
    removed = [
        c
        for c in list(tbl.constraints)
        if isinstance(c, UniqueConstraint) and [col.name for col in c.columns] == ["addr"]
    ]
    for c in removed:
        tbl.constraints.discard(c)
    eng = create_engine("sqlite:///:memory:")
    try:
        Base.metadata.create_all(eng)
    finally:
        for c in removed:
            tbl.constraints.add(c)

    with Session(eng) as sess:
        shared, i1, i2 = _seed_two_hosts_with_same_addr(sess)

        # The primitive returns BOTH interfaces — pairwise, no crash.
        found = resolve_interfaces(sess, shared)
        assert found == {i1, i2}
        assert {i.host.domain for i in found} == {"anyc-a.example", "anyc-b.example"}

        # resolve_hosts collapses to the two owning hosts.
        assert {h.domain for h in resolve_hosts(sess, shared)} == {
            "anyc-a.example",
            "anyc-b.example",
        }

        # resolve_one insists on uniqueness and raises, carrying the pair.
        with pytest.raises(AmbiguousAddress) as ei:
            resolve_one(sess, shared)
        assert ei.value.candidates == {i1, i2}
        assert ei.value.addr == shared

        # Strict mode behaves identically for a routable (non-link-local)
        # address: duplicates are a property of the data, not the mode.
        assert resolve_interfaces(sess, shared, strict=True) == {i1, i2}

    eng.dispose()
