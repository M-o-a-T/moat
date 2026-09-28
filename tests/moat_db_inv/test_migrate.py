"""
Tests for ``moat db inv migrate-from-kv``, using a small MoaT-KV inventory dump.
"""

from __future__ import annotations

import pytest
from pathlib import Path

import asyncclick as click
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

import moat.db.inv.model_  # noqa: F401  — wires the Thing relationships
import moat.db.util  # noqa: F401  — sqlite foreign_keys pragma
from moat.util import yload
from moat.db.inv.ip import IpValue
from moat.db.inv.model import Address, Cable, Host, HostGroup, Interface, Network, Vlan
from moat.src.test import raises, run

DUMP = Path(__file__).parent / "data" / "kv_inv.yaml"


@pytest.fixture
async def db_url(tmp_path):
    "an empty database with the full schema"
    url = f"sqlite:///{tmp_path / 'inv.db'}"
    await run("-s", "moat.db.url", url, "db", "init")
    return url


async def _migrate(url, *args):
    return await run(
        "-s", "moat.db.url", url, "db", "inv", "migrate-from-kv", "-i", str(DUMP), *args
    )


def _addrs(i: Interface) -> list[str]:
    return sorted(str(a.ip.ip) for a in i.addresses)


@pytest.mark.anyio
async def test_migrate(db_url):
    "the dump is imported; problems are reported"
    res = await _migrate(db_url)
    rep = yload(res.stdout)

    assert rep["counts"] == {
        "vlan": 2,
        "network": 4,
        "host": 5,
        "wire": 1,
        "interface": 10,
        "group": 1,
        "cable": 3,
        "address": 6,
    }
    assert rep["skipped"] == [
        "net ten (10.0.0.0/8): no VLAN",
        "iface ghost.lan.example:en0: unknown net 'nonexistent'",
        "cable host.example.lan.gone:en0 – host.example.lan.sw:2: endpoint missing",
    ]
    assert (
        "iface clash.lan.example:en0: seqnum 10 on std already used by srv.lan.example:en0, dropped"
        in rep["changed"]
    )
    assert "net std4: wlan moved to VLAN std" in rep["changed"]
    assert rep["expanded"] == [
        "srv.lan.example:en0: std4, std6",
        "pi.lan.example:.: std4, std6",
    ]
    assert rep["attrs"] == ["srv.lan.example:en1: {'extra': 42}"]

    eng = create_engine(db_url)
    with Session(eng) as s:
        std = s.execute(select(Vlan).where(Vlan.name == "std")).scalar_one()
        assert (std.tag, std.wlan, std.passwd) == (10, "Home", "secret")
        n4 = s.execute(select(Network).where(Network.name == "std4")).scalar_one()
        assert (str(n4.subnet.net), n4.dhcp_first, n4.dhcp_count) == ("192.168.1.0/24", 100, 50)

        srv = s.execute(select(Host).where(Host.domain == "srv.lan.example")).scalar_one()
        assert (srv.thing.name, srv.thing.descr, srv.loc) == ("srv", "a server", "basement")
        assert [g.name for g in srv.groups] == ["servers"]
        ifs = {i.name: i for i in srv.interfaces}
        assert str(ifs["en0"].mac) == "02-00-00-00-00-01"
        assert _addrs(ifs["en0"]) == ["192.168.1.10/24", "2001:db8:0:1::a/64"]
        assert (ifs["en1"].vlan.name, ifs["en1"].seqnum) == ("infra", 7)
        assert _addrs(ifs["en1"]) == ["192.168.2.7/24", "2001:db8:0:2::7/64"]  # slave net

        pi = s.execute(select(Host).where(Host.domain == "pi.lan.example")).scalar_one()
        (direct,) = pi.interfaces
        assert (direct.name, direct.seqnum) == ("", 11)

        sw = s.execute(select(Host).where(Host.domain == "sw.lan.example")).scalar_one()
        assert {i.name: i.vlan and i.vlan.name for i in sw.interfaces} == {
            "1": None,
            "2": "infra",
            "3": None,
        }

        w1 = s.execute(select(Host).where(Host.domain == "w1")).scalar_one()
        assert (w1.thing.thingtyp.name, w1.loc) == ("wire", "wall")
        cables = {
            (
                f"{c.iface_a.host.domain}:{c.iface_a.name}",
                f"{c.iface_b.host.domain}:{c.iface_b.name}",
            )
            for c in s.execute(select(Cable)).scalars()
        }
        assert cables == {
            ("srv.lan.example:en0", "sw.lan.example:1"),
            ("pi.lan.example:", "w1:a"),
            ("w1:b", "sw.lan.example:3"),
        }
        assert s.execute(select(HostGroup)).scalar_one().name == "servers"
    eng.dispose()

    # a second import is refused
    with raises(click.UsageError):
        await _migrate(db_url)


@pytest.mark.anyio
async def test_dry_run(db_url):
    "a dry run reports but stores nothing"
    rep = yload((await _migrate(db_url, "-n")).stdout)
    assert rep["counts"]["host"] == 5
    eng = create_engine(db_url)
    with Session(eng) as s:
        assert s.execute(select(Host)).first() is None
        assert s.execute(select(Vlan)).first() is None
    eng.dispose()


@pytest.mark.anyio
async def test_select_by_name(db_url):
    "'-n NAME' selects a host or wire by its short name"
    await _migrate(db_url)

    async def show(*args):
        return (await run("-s", "moat.db.url", db_url, "db", "inv", *args, "show")).stdout

    assert await show("host", "-n", "srv") == await show("host", "-d", "srv.lan.example")
    assert "srv.lan.example" in await show("host", "-n", "srv")
    assert await show("wire", "-n", "w1") == await show("wire", "-d", "w1")
    assert await show("vlan", "-n", "std") == await show("vlan", "-t", "10")
    assert "10\tstd" in await show("vlan")
    nocmd = await run("-s", "moat.db.url", db_url, "db", "inv", "vlan", "-n", "std")
    assert nocmd.stdout == await show("vlan", "-n", "std")  # 'show' is the default
    assert await show("net", "-a", "192.168.1.77") == await show("net", "-n", "std4")
    assert await show("net", "-a", "2001:db8:0:1::5") == await show("net", "-n", "std6")
    assert (await show("host", "-n", "srv", "iface", "-")).split("\n")[:2] == [
        "en0 std 02-00-00-00-00-01",
        "en1 infra -",
    ]
    assert "seqnum: 11" in await show("host", "-n", "pi", "iface", ".")
    with raises(click.UsageError):
        await show("net", "-a", "172.16.0.1")
    with raises(click.UsageError):
        await show("host", "-n", "nope")
    with raises(click.UsageError):
        await show("host", "-n", "srv", "-d", "srv.lan.example")


@pytest.mark.anyio
async def test_select_by_addr(db_url):
    "'-a ADDR' selects the host (or interface) that owns an IP address"
    await _migrate(db_url)

    async def show(*args):
        return (await run("-s", "moat.db.url", db_url, "db", "inv", *args, "show")).stdout

    # srv.lan.example:en0 owns 192.168.1.10/24 and 2001:db8:0:1::a/64;
    # srv.lan.example:en1 owns 192.168.2.7/24. All three resolve to srv.
    for addr in ("192.168.1.10", "2001:db8:0:1::a", "192.168.2.7"):
        assert await show("host", "-a", addr) == await show("host", "-d", "srv.lan.example")

    # '-a' agrees with '-n' for the same host.
    assert await show("host", "-a", "192.168.1.10") == await show("host", "-n", "srv")

    # 'host -a ADDR iface -a ADDR .' pins both host and interface to the owner.
    assert await show("host", "-a", "192.168.1.10", "iface", "-a", "192.168.1.10", ".") == (
        await show("host", "-d", "srv.lan.example", "iface", "en0")
    )
    # '-a' may supply the host too (no outer selector needed).
    assert await show("host", "iface", "-a", "192.168.2.7", ".") == await show(
        "host", "-d", "srv.lan.example", "iface", "en1"
    )
    # '-' is accepted as the placeholder interface name alongside '-a'.
    assert await show("host", "iface", "-a", "192.168.1.10", "-") == await show(
        "host", "-d", "srv.lan.example", "iface", "en0"
    )

    # Errors: no owner, garbage, and selector exclusivity.
    with raises(click.UsageError):
        await show("host", "-a", "10.255.255.1")
    with raises(click.UsageError):
        await show("host", "-a", "not.an.address")
    with raises(click.UsageError):
        await show("host", "-a", "192.168.1.10", "-d", "srv.lan.example")
    with raises(click.UsageError):
        await show("host", "-a", "192.168.1.10", "-n", "srv")
    with raises(click.UsageError):
        await show("host", "-n", "srv", "iface", "-a", "192.168.1.10", "en0")
    with raises(click.UsageError):
        await show("host", "-n", "srv", "iface", "-a", "10.255.255.1", ".")


@pytest.mark.anyio
async def test_select_by_addr_anycast(tmp_path):
    "'-a ADDR' errors when several hosts/interfaces own the address"
    # The schema marks Address.addr UNIQUE, so a genuine duplicate requires
    # relaxing that constraint on the shared metadata before the file DB is
    # created — mirroring tests/moat_db_inv/test_resolve.py's anycast axis.
    from sqlalchemy import UniqueConstraint  # noqa: PLC0415

    from moat.db.util import load_schemas  # noqa: PLC0415

    load_schemas()
    tbl = Address.__table__
    removed = [
        c
        for c in list(tbl.constraints)
        if isinstance(c, UniqueConstraint) and [col.name for col in c.columns] == ["addr"]
    ]
    for c in removed:
        tbl.constraints.discard(c)
    url = f"sqlite:///{tmp_path / 'anycast.db'}"
    try:
        await run("-s", "moat.db.url", url, "db", "init")
    finally:
        for c in removed:
            tbl.constraints.add(c)

    eng = create_engine(url)
    with Session(eng) as s:
        from moat.db.thing.model import Thing, ThingTyp  # noqa: PLC0415

        tt = ThingTyp(name="host", abstract=False)
        s.add(tt)
        s.flush()
        t1 = Thing(name="anyc-a", thingtyp=tt)
        t2 = Thing(name="anyc-b", thingtyp=tt)
        s.add_all([t1, t2])
        s.flush()
        h1 = Host(domain="anyc-a.example", thing=t1)
        h2 = Host(domain="anyc-b.example", thing=t2)
        s.add_all([h1, h2])
        s.flush()
        i1 = Interface(host=h1, name="")
        i2 = Interface(host=h2, name="")
        s.add_all([i1, i2])
        s.flush()
        key = IpValue.from_ip("203.0.113.42").addr
        s.add(Address(interface=i1, addr=key, prefix=None))
        s.add(Address(interface=i2, addr=key, prefix=None))
        s.commit()
    eng.dispose()

    async def show(*args):
        return (await run("-s", "moat.db.url", url, "db", "inv", *args, "show")).stdout

    # Both 'host -a' and 'iface -a' refuse, naming the contenders.
    with raises(click.UsageError) as exc:
        await show("host", "-a", "203.0.113.42")
    assert "2 hosts" in str(exc.value)
    assert "anyc-a.example" in str(exc.value)

    with raises(click.UsageError) as exc:
        await show("host", "iface", "-a", "203.0.113.42", ".")
    assert "2 interfaces" in str(exc.value)
    assert "anyc-a.example:." in str(exc.value)
