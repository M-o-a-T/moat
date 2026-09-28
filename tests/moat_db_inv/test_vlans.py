"""
Tests for :mod:`moat.db.inv.vlans` — the per-interface VLAN exposure
collector.

Axes follow the issue's check dimensions:

* override-beats-implied precedence — an interface's own VLAN stamp is the
  VLAN collected, even when it carries no sequence number;
* union-across-stacked-nets breadth — a VLAN bearing two networks still
  contributes that one VLAN (not zero, not duplicated);
* traversal terminating through one and two sequential wire crossings;
* cycle immunity — a loop in the cable graph is walked once, not forever;
* blank result for a lone unbonded interface;
* stability of ordering across repeated evaluations on unchanged data.

Realistic axes run against the database populated by ``mt db inv
migrate-from-kv`` from the small DistKV fixture, so the collector is
exercised against the real population path. Synthetic axes (two-wire
series, cycle, stacked-net isolation) build a minimal topology by hand on
an in-memory schema, controlling exactly which rows exist.
"""

from __future__ import annotations

import pytest
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

import moat.db.inv.model_  # noqa: F401  — wires the Thing relationships
import moat.db.util  # noqa: F401  — sqlite foreign_keys pragma
from moat.db.inv.model import Cable, Host, Interface, Vlan
from moat.db.inv.vlans import connected_vlans
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

    The collector ducks the session (it walks ORM relationships hung off the
    interface argument), so a plain ``Session`` works just as well as the
    CLI's :class:`~moat.db.util.Mgr`.
    """
    eng = create_engine(url)
    sess = Session(eng)
    return sess, eng


def _iface(sess, domain, name) -> Interface:
    """Look up an interface by ``host.domain`` and interface name."""
    h = sess.execute(select(Host).where(Host.domain == domain)).scalar_one()
    return sess.execute(
        select(Interface).where(Interface.host == h, Interface.name == name)
    ).scalar_one()


def _names(vlans: set[Vlan]) -> set[str]:
    """VLAN rows → their names, for assertion-friendly comparisons."""
    return {v.name for v in vlans}


# ---------------------------------------------------------------------------
# Realistic axes against the migrated DB
# ---------------------------------------------------------------------------
#
# Fixture topology (tests/moat_db_inv/data/kv_inv.yaml, post-migration):
#   VLANs: std(10, nets std4+std6), infra(20, nets infra4+infra6).
#   srv.lan.example: en0 (std, cabled to sw:1), en1 (infra, uncabled).
#   pi.lan.example: "" (std, cabled to w1:a).
#   clash.lan.example: en0 (std, no seqnum — dup-dropped, uncabled).
#   sw.lan.example: 1 (no vlan, cabled to srv:en0),
#                   2 (infra, uncabled — its cable endpoint was missing),
#                   3 (no vlan, cabled to w1:b).
#   ghost.lan.example: en0 (no vlan, unknown net, uncabled).
#   w1 (wire): a (cabled to pi:""), b (cabled to sw:3).
#   Cables: srv:en0↔sw:1, pi:""↔w1:a, w1:b↔sw:3.


@pytest.mark.anyio
async def test_origin_crosses_switch_to_dual_vlan_host(populated_url):
    "sw:1 (no own VLAN) reaches srv, whose en0/en1 carry std and infra."
    sess, eng = _session(populated_url)
    try:
        i = _iface(sess, "sw.lan.example", "1")
        assert _names(connected_vlans(sess, i)) == {"std", "infra"}
    finally:
        sess.close()
        eng.dispose()


@pytest.mark.anyio
async def test_single_wire_crossing(populated_url):
    "sw:3 crosses one wire (w1) to pi, which carries only std."
    sess, eng = _session(populated_url)
    try:
        i = _iface(sess, "sw.lan.example", "3")
        assert _names(connected_vlans(sess, i)) == {"std"}
    finally:
        sess.close()
        eng.dispose()


@pytest.mark.anyio
async def test_override_beats_implied(populated_url):
    "clash:en0 has its VLAN stamped std despite its seqnum being dropped."
    sess, eng = _session(populated_url)
    try:
        i = _iface(sess, "clash.lan.example", "en0")
        # The stamp dominates; the interface is uncabled, so only std.
        assert _names(connected_vlans(sess, i)) == {"std"}
        assert i.seqnum is None  # sanity: the stamp survived without a seqnum
    finally:
        sess.close()
        eng.dispose()


@pytest.mark.anyio
async def test_union_across_stacked_nets(populated_url):
    "std carries two networks (std4, std6) yet contributes the one VLAN."
    sess, eng = _session(populated_url)
    try:
        std = sess.execute(select(Vlan).where(Vlan.name == "std")).scalar_one()
        net_names = {n.name for n in std.networks}
        assert net_names == {"std4", "std6"}  # sanity: really stacked

        # clash:en0 is stamped onto the stacked VLAN std (and is uncabled,
        # so nothing else bleeds in). Stacked nets broaden exposure to the
        # VLAN, not beyond it: std appears once, not twice and not zero.
        i = _iface(sess, "clash.lan.example", "en0")
        result = connected_vlans(sess, i)
        assert _names(result) == {"std"}
        assert sum(1 for v in result if v.name == "std") == 1
    finally:
        sess.close()
        eng.dispose()


@pytest.mark.anyio
async def test_blank_result_for_lone_unbonded(populated_url):
    "ghost:en0 has no VLAN and no cable → empty exposure."
    sess, eng = _session(populated_url)
    try:
        i = _iface(sess, "ghost.lan.example", "en0")
        assert connected_vlans(sess, i) == set()
    finally:
        sess.close()
        eng.dispose()


@pytest.mark.anyio
async def test_stamping_does_not_halt_traversal(populated_url):
    "a stamped, cabled interface still propagates downstream (deviation note)."
    sess, eng = _session(populated_url)
    try:
        # srv:en0 is stamped std AND cabled to sw:1; the walk continues
        # through it to sw's other ports (sw:2 → infra, sw:3 → pi/std).
        i = _iface(sess, "srv.lan.example", "en0")
        assert _names(connected_vlans(sess, i)) == {"std", "infra"}
    finally:
        sess.close()
        eng.dispose()


@pytest.mark.anyio
async def test_ordering_stability(populated_url):
    "two evaluations on unchanged data compare equal (sets are order-free)."
    sess, eng = _session(populated_url)
    try:
        i = _iface(sess, "sw.lan.example", "1")
        a = connected_vlans(sess, i)
        b = connected_vlans(sess, i)
        assert a == b
        assert a is not b  # fresh collection each call, not a cached object
    finally:
        sess.close()
        eng.dispose()


# ---------------------------------------------------------------------------
# Synthetic axes — hand-built topologies on an in-memory schema
# ---------------------------------------------------------------------------


def _seed_topology():
    """Build a fresh in-memory DB and return ``(engine, sess)``.

    Constructs the full ``moat.db.inv`` schema on a throwaway SQLite engine
    so the synthetic axes control exactly which rows exist. Caller owns
    closing both.
    """
    from moat.db.schema import Base  # noqa: PLC0415
    from moat.db.util import load_schemas  # noqa: PLC0415

    load_schemas()  # ensure all models are imported (FK targets exist)
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    sess = Session(eng)
    return eng, sess


def _mk_world(sess, *, vlans, hosts, cables):
    """Seed a tiny world.

    Args:
        vlans: iterable of VLAN names to create (tags assigned in order).
        hosts: iterable of ``(name, thingtyp, [(iface, vlan_or_None)])``.
        cables: iterable of ``(hostA:ifaceA, hostB:ifaceB)`` specs.
    """
    from moat.db.thing.model import Thing, ThingTyp  # noqa: PLC0415

    ttyps = {}
    for tn in ("host", "wire"):
        t = ThingTyp(name=tn, abstract=False)
        sess.add(t)
        ttyps[tn] = t
    sess.flush()

    vmap: dict[str, Vlan] = {}
    for idx, vn in enumerate(vlans, start=10):
        v = Vlan(tag=idx, name=vn)
        sess.add(v)
        vmap[vn] = v
    sess.flush()

    hmap: dict[str, Host] = {}
    imap: dict[tuple[str, str], Interface] = {}
    for name, ttyp, ifs in hosts:
        tt = ttyps[ttyp]
        thing = Thing(name=name, thingtyp=tt)
        sess.add(thing)
        sess.flush()
        h = Host(domain=name, thing=thing)
        sess.add(h)
        sess.flush()
        hmap[name] = h
        for iname, vname in ifs:
            ivlan = None if vname is None else vmap[vname]
            iface = Interface(host=h, name=iname, vlan=ivlan)
            sess.add(iface)
            imap[(name, iname)] = iface
    sess.flush()

    for aspec, bspec in cables:
        a = imap[_split_spec(aspec)]
        b = imap[_split_spec(bspec)]
        sess.add(Cable(iface_a=a, iface_b=b))
    sess.commit()
    return hmap, imap


def _split_spec(spec):
    """``"host:iface"`` → ``("host", "iface")`` (empty iface name allowed)."""
    h, i = spec.split(":", 1)
    return (h, "" if i == "." else i)


def test_two_sequential_wire_crossings():
    "two wires chained in series are crossed as two ordinary host hops."
    eng, sess = _seed_topology()
    try:
        _mk_world(
            sess,
            vlans=["mgmt"],
            hosts=[
                ("sw", "host", [("1", None), ("2", None)]),
                ("w1", "wire", [("a", None), ("b", None)]),
                ("w2", "wire", [("a", None), ("b", None)]),
                ("srv", "host", [("", "mgmt")]),
            ],
            cables=[
                ("sw:1", "w1:a"),
                ("w1:b", "w2:a"),
                ("w2:b", "srv:."),
            ],
        )
        i = sess.execute(
            select(Interface).join(Host).where(Host.domain == "sw", Interface.name == "1")
        ).scalar_one()
        # sw:1 → w1 → w2 → srv("") mgmt: two wire bodies crossed, one VLAN.
        assert _names(connected_vlans(sess, i)) == {"mgmt"}
    finally:
        sess.close()
        eng.dispose()


def test_cycle_immunity():
    "a diamond in the cable graph is walked once and terminates."
    eng, sess = _seed_topology()
    try:
        # Diamond reconverging at srv (NOT the origin host, so the
        # origin-sibling shielding does not muddy the result):
        #   sw:1 --- ha:p1
        #   ha:p2 --- hb:p1 --- hb:p2(red) --- srv:en0
        #   ha:p3 --- hc:p1 --- hc:p2(blue) --- srv:en1
        # srv is reached by both branches; it must be swept exactly once.
        _mk_world(
            sess,
            vlans=["red", "blue"],
            hosts=[
                ("sw", "host", [("1", None)]),
                ("ha", "host", [("p1", None), ("p2", None), ("p3", None)]),
                ("hb", "host", [("p1", None), ("p2", "red")]),
                ("hc", "host", [("p1", None), ("p2", "blue")]),
                ("srv", "host", [("en0", None), ("en1", None)]),
            ],
            cables=[
                ("sw:1", "ha:p1"),
                ("ha:p2", "hb:p1"),
                ("ha:p3", "hc:p1"),
                ("hb:p2", "srv:en0"),
                ("hc:p2", "srv:en1"),
            ],
        )
        i = sess.execute(
            select(Interface).join(Host).where(Host.domain == "sw", Interface.name == "1")
        ).scalar_one()
        # Both branches' VLANs are harvested; srv (no VLAN) is swept once.
        assert _names(connected_vlans(sess, i)) == {"red", "blue"}
    finally:
        sess.close()
        eng.dispose()


def test_empty_database_returns_nothing():
    "an interface with no cables and no VLAN yields an empty set."
    eng, sess = _seed_topology()
    try:
        _mk_world(
            sess,
            vlans=[],
            hosts=[("lonely", "host", [("eth0", None)])],
            cables=[],
        )
        i = sess.execute(
            select(Interface).join(Host).where(Host.domain == "lonely", Interface.name == "eth0")
        ).scalar_one()
        assert connected_vlans(sess, i) == set()
    finally:
        sess.close()
        eng.dispose()


def test_origin_siblings_are_separate_segments():
    "the origin's sibling interfaces are NOT swept (separate segments)."
    eng, sess = _seed_topology()
    try:
        # sw has three ports; only sw:1 is cabled outward (to srv:red).
        # sw:2 (blue) and sw:3 (green) are uncabled siblings. Querying sw:1
        # must NOT pick up sw:2/sw:3 — they are different segments.
        _mk_world(
            sess,
            vlans=["red", "blue", "green"],
            hosts=[
                ("sw", "host", [("1", None), ("2", "blue"), ("3", "green")]),
                ("srv", "host", [("", "red")]),
            ],
            cables=[("sw:1", "srv:.")],
        )
        i = sess.execute(
            select(Interface).join(Host).where(Host.domain == "sw", Interface.name == "1")
        ).scalar_one()
        assert _names(connected_vlans(sess, i)) == {"red"}
    finally:
        sess.close()
        eng.dispose()


def test_far_host_siblings_are_swept():
    "a far host reached across a cable IS swept across all its interfaces."
    eng, sess = _seed_topology()
    try:
        # sw:1 cabled to hub:p1; hub has p2(red, cabled to a), p3(blue, cabled to b).
        # Querying sw:1 reaches hub and sweeps p2,p3 → red and blue.
        _mk_world(
            sess,
            vlans=["red", "blue"],
            hosts=[
                ("sw", "host", [("1", None)]),
                ("hub", "host", [("p1", None), ("p2", "red"), ("p3", "blue")]),
                ("a", "host", [("", None)]),
                ("b", "host", [("", None)]),
            ],
            cables=[("sw:1", "hub:p1"), ("hub:p2", "a:."), ("hub:p3", "b:.")],
        )
        i = sess.execute(
            select(Interface).join(Host).where(Host.domain == "sw", Interface.name == "1")
        ).scalar_one()
        assert _names(connected_vlans(sess, i)) == {"red", "blue"}
    finally:
        sess.close()
        eng.dispose()
