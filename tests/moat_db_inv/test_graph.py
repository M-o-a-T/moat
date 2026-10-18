"""Tests for :mod:`moat.db.inv.graph` — the reachability walker.

Axes from the issue:

* a bare cable hop (``srv:en0`` → the switch),
* a hop crossing a wire host (``pi`` → ``w1`` → ``sw``), proving no
  infinite bounce through the wire's two interfaces,
* a diamond revisited once (synthetic ring topology),
* an isolated host yielding itself only,
* an empty database returning nothing.

The realistic axes run against the migrated fixture database (see
``data/kv_inv.yaml``), whose topology is::

    srv:en0 ──cable── sw:1
    pi ──────cable── w1:a   w1:b ──cable── sw:3
    sw:2 (dangling)

so walking from ``srv:en0`` must traverse the wire ``w1`` to reach ``pi``
and prove that the walk terminates.
"""

from __future__ import annotations

import pytest
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

import moat.db.inv.model_  # noqa: F401  — wires the Thing relationships
import moat.db.util  # noqa: F401  — sqlite foreign_keys pragma
from moat.db.inv.graph import connected_hosts
from moat.db.inv.ip import IpValue
from moat.db.inv.model import (
    Address,
    Cable,
    Host,
    Interface,
    Network,
    Vlan,
)
from moat.db.thing.model import Thing, ThingTyp
from moat.src.test import run

DUMP = Path(__file__).parent / "data" / "kv_inv.yaml"


@pytest.fixture
async def db_url(tmp_path):
    "an empty database with the full schema, stamped to head"
    url = f"sqlite:///{tmp_path / 'inv.db'}"
    await run("-s", "moat.db.url", url, "db", "init")
    return url


@pytest.fixture
async def populated_url(db_url):
    "a database initialised and populated by the migrator"
    await run("-s", "moat.db.url", db_url, "db", "inv", "migrate-from-kv", "-i", str(DUMP))
    return db_url


def _session(url):
    "a bare Session on the file DB; closing the engine is the caller's job"
    eng = create_engine(url)
    return Session(eng), eng


def _host(sess, domain):
    return sess.execute(select(Host).where(Host.domain == domain)).scalar_one()


def _iface(sess, domain, name):
    return sess.execute(
        select(Interface).where(
            Interface.name == name, Interface.host_id == _host(sess, domain).id
        )
    ).scalar_one()


def _domains(nodes):
    "the domains of the hosts among ``nodes``"
    return {n.domain for n in nodes if isinstance(n, Host)}


# ---------------------------------------------------------------------------
# Realistic axes against the migrated DB
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_cable_hop_and_route(populated_url):
    "a bare cable hop: the origin, its host, the partner, and the far host."
    sess, eng = _session(populated_url)
    try:
        en0 = _iface(sess, "srv.lan.example", "en0")
        walked = list(connected_hosts(sess, en0))

        # The origin leads, with an empty chain.
        node, hops = walked[0]
        assert node is en0
        assert hops == ()

        # Every node is yielded once.
        keys = [(n.__class__.__name__, n.id) for n, _ in walked]
        assert len(keys) == len(set(keys))

        # Reachable: the whole component — srv, the switch, the wire,
        # and pi behind it (sw:3 continues into w1).
        assert _domains([n for n, _ in walked]) == {
            "srv.lan.example",
            "sw.lan.example",
            "w1",
            "pi.lan.example",
        }

        # The route to the switch's port 1 crosses the cable: its chain
        # holds the origin interface (the direct cable edge).
        sw1 = _iface(sess, "sw.lan.example", "1")
        chains = {n.id: h for n, h in walked if isinstance(n, Interface)}
        assert chains[sw1.id] == (en0,)

        # The dangling port sw:2 is on the switch, so it IS reachable
        # (the host fan-out visits every interface) — but nothing beyond.
        sw2 = _iface(sess, "sw.lan.example", "2")
        assert sw2.id in chains
    finally:
        sess.close()
        eng.dispose()


@pytest.mark.anyio
async def test_wire_transit_no_bounce(populated_url):
    "crossing a wire is two host hops; the walk terminates."
    sess, eng = _session(populated_url)
    try:
        pi = _host(sess, "pi.lan.example")
        walked = list(connected_hosts(sess, pi))

        # The whole component is reached — through the wire to the
        # switch, and onward to srv.
        assert _domains([n for n, _ in walked]) == {
            "pi.lan.example",
            "w1",
            "sw.lan.example",
            "srv.lan.example",
        }

        # Terminates: every node once, finite list.
        keys = [(n.__class__.__name__, n.id) for n, _ in walked]
        assert len(keys) == len(set(keys))

        # The route to sw:3 passes the wire's b interface and the wire
        # host — two ordinary hops, no special case.
        w1 = _host(sess, "w1")
        sw3 = _iface(sess, "sw.lan.example", "3")
        wb = _iface(sess, "w1", "b")
        chains = {n.id: h for n, h in walked if isinstance(n, Interface)}
        assert wb in chains[sw3.id]
        assert w1 in chains[sw3.id]

        # And from the far side, the walk crosses back symmetrically.
        back = list(connected_hosts(sess, sw3))
        assert _domains([n for n, _ in back]) == {
            "pi.lan.example",
            "w1",
            "sw.lan.example",
            "srv.lan.example",
        }
    finally:
        sess.close()
        eng.dispose()


@pytest.mark.anyio
async def test_isolated_host_yields_self_only(populated_url):
    "a host with no cables yields itself and its interfaces, nothing else."
    sess, eng = _session(populated_url)
    try:
        clash = _host(sess, "clash.lan.example")
        walked = list(connected_hosts(sess, clash))
        assert _domains([n for n, _ in walked]) == {"clash.lan.example"}
        # its lone interface, plus the host itself
        assert len(walked) == 2
    finally:
        sess.close()
        eng.dispose()


@pytest.mark.anyio
async def test_empty_database_returns_nothing(db_url):
    "walking any node of an empty database yields nothing."
    sess, eng = _session(db_url)
    try:
        phantom = Interface(id=999999, host_id=1, name="x")
        assert list(connected_hosts(sess, phantom)) == []
    finally:
        sess.close()
        eng.dispose()


# ---------------------------------------------------------------------------
# Synthetic topologies
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_bare_cable_hop(db_url):
    """Two hosts, one cable: the minimal hop.

    The origin interface yields itself, its host, the partner interface,
    and the far host — nothing else.
    """
    sess, eng = _session(db_url)
    try:
        ha, hb = _mk_host(sess, "a.pair.example"), _mk_host(sess, "b.pair.example")
        ia = Interface(host=ha, name="eth0")
        ib = Interface(host=hb, name="eth0")
        sess.add_all((ia, ib))
        sess.add(Cable(iface_a=ia, iface_b=ib))
        sess.commit()

        walked = list(connected_hosts(sess, ia))
        assert len(walked) == 4
        assert walked[0][0] is ia
        assert walked[0][1] == ()
        # breadth-first: the two distance-1 nodes (the cable partner and
        # the owning host) precede the distance-2 far host
        assert [type(n).__name__ for n, _ in walked] == [
            "Interface",
            "Interface",
            "Host",
            "Host",
        ]
        assert _domains([n for n, _ in walked]) == {"a.pair.example", "b.pair.example"}

        # the far host's chain crosses the cable: origin → partner
        far = walked[3]
        assert far[0] is hb
        assert far[1] == (ia, ib)
    finally:
        sess.close()
        eng.dispose()


def _mk_host(sess, domain, name=None, typ="host"):
    """Create a Host with its mandatory backing Thing.

    Direct construction (rather than ``Host.apply``) keeps the synthetic
    tests independent of the ambient-session machinery.
    """
    ttyp = sess.execute(select(ThingTyp).where(ThingTyp.name == typ)).scalar_one_or_none()
    if ttyp is None:
        ttyp = ThingTyp(name=typ)
        sess.add(ttyp)
    h = Host(domain=domain)
    sess.add(h)
    h.thing = Thing(name=name if name is not None else domain.split(".")[0], thingtyp=ttyp)
    return h


def _diamond(sess):
    """Build a diamond: two cable paths between hosts A and B.

    ::

        A.i1 --cable-- hub1.i1    hub1.i2 --cable-- B.i1
        A.i2 --cable-- hub2.i1    hub2.i2 --cable-- B.i2

    B is reachable along two routes; it must be yielded once. Returns A.
    """
    a, b = _mk_host(sess, "a.diamond.example"), _mk_host(sess, "b.diamond.example")
    h1, h2 = _mk_host(sess, "hub1.diamond.example"), _mk_host(sess, "hub2.diamond.example")
    ai1, ai2 = Interface(host=a, name="i1"), Interface(host=a, name="i2")
    bi1, bi2 = Interface(host=b, name="i1"), Interface(host=b, name="i2")
    h1i1, h1i2 = Interface(host=h1, name="i1"), Interface(host=h1, name="i2")
    h2i1, h2i2 = Interface(host=h2, name="i1"), Interface(host=h2, name="i2")
    for i in (ai1, ai2, bi1, bi2, h1i1, h1i2, h2i1, h2i2):
        sess.add(i)
    for x, y in ((ai1, h1i1), (h1i2, bi1), (ai2, h2i1), (h2i2, bi2)):
        sess.add(Cable(iface_a=x, iface_b=y))
    sess.flush()
    return a


@pytest.mark.anyio
async def test_diamond_visited_once(db_url):
    "a diamond: every node is yielded exactly once; the walk terminates."
    sess, eng = _session(db_url)
    try:
        a = _diamond(sess)
        sess.commit()
        walked = list(connected_hosts(sess, a))
        keys = [(n.__class__.__name__, n.id) for n, _ in walked]
        assert len(keys) == len(set(keys))
        # 4 hosts + 8 interfaces
        assert len(walked) == 12
        assert _domains([n for n, _ in walked]) == {
            "a.diamond.example",
            "b.diamond.example",
            "hub1.diamond.example",
            "hub2.diamond.example",
        }
        # B is yielded exactly once - diamonds terminate.
        b = _host(sess, "b.diamond.example")
        assert sum(n is b for n, _ in walked) == 1
    finally:
        sess.close()
        eng.dispose()


@pytest.mark.anyio
async def test_virtual_network_edges(db_url):
    "interfaces on a virtual network are adjacent without a cable."
    sess, eng = _session(db_url)
    try:
        vlan = Vlan(tag=99, name="vnet")
        sess.add(vlan)
        net = Network(
            name="vnet4",
            vlan=vlan,
            addr=IpValue.from_ip("10.99.0.0/24").addr,
            prefix=24,
            virt=True,
        )
        sess.add(net)

        ha, hb = _mk_host(sess, "va.example"), _mk_host(sess, "vb.example")
        ia = Interface(host=ha, name="eth0")
        ib = Interface(host=hb, name="eth0")
        sess.add_all((ia, ib))
        sess.add_all((
            Address(interface=ia, addr=IpValue.from_ip("10.99.0.1").addr, prefix=24),
            Address(interface=ib, addr=IpValue.from_ip("10.99.0.2").addr, prefix=24),
        ))
        sess.commit()

        walked = list(connected_hosts(sess, ia))
        assert _domains([n for n, _ in walked]) == {"va.example", "vb.example"}

        # The far interface is reached directly, its chain holding the
        # origin (virtual-network adjacency, no cable in between).
        chains = {n.id: h for n, h in walked if isinstance(n, Interface)}
        assert ia in chains[ib.id]
    finally:
        sess.close()
        eng.dispose()
