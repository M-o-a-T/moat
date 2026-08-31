"""
Tests for :mod:`moat.db.inv.ip`.

Covers the IPv4-mapped-into-IPv6 address encoding, the :class:`IpValue`
composite value, the :class:`MacAddr` column type, and the EUI-64
link-local helpers, including a SQLAlchemy round-trip on in-memory SQLite.
"""

from __future__ import annotations

import ipaddress
import pytest

from netaddr import EUI
from sqlalchemy import LargeBinary, SmallInteger, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, composite, mapped_column

from moat.db.inv.ip import IpValue, MacAddr, is_mac_link_local, link_local_from_mac


class _Base(DeclarativeBase):
    pass


class _Row(_Base):
    __tablename__ = "row"

    id: Mapped[int] = mapped_column(primary_key=True)
    addr: Mapped[bytes] = mapped_column(LargeBinary(16))
    prefix: Mapped[int | None] = mapped_column(SmallInteger)
    ip: Mapped[IpValue] = composite(IpValue, "addr", "prefix")
    mac: Mapped[EUI | None] = mapped_column(MacAddr, nullable=True)


@pytest.fixture
def eng():
    "In-memory SQLite engine with the test schema; disposed after each test."
    e = create_engine("sqlite:///:memory:")
    _Base.metadata.create_all(e)
    try:
        yield e
    finally:
        e.dispose()


def test_from_ip_v4_mapping():
    "IPv4 addresses are stored IPv4-mapped and decode back to v4."
    v = IpValue.from_ip("10.0.0.5/24")
    assert v.addr == bytes.fromhex("00000000000000000000ffff0a000005")
    assert v.prefix == 24
    assert v.ip == ipaddress.ip_interface("10.0.0.5/24")
    assert v.net == ipaddress.ip_network("10.0.0.0/24")


def test_from_ip_v6_native():
    "Native IPv6 addresses pass through; a bare address has no prefix."
    v = IpValue.from_ip(ipaddress.IPv6Address("2001:db8::1"))
    assert v.addr == bytes.fromhex("20010db8000000000000000000000001")
    assert v.prefix is None
    assert v.ip == ipaddress.IPv6Address("2001:db8::1")
    with pytest.raises(ValueError):  # noqa:PT011
        _ = v.net


def test_from_ip_network():
    "Network objects store the network address and prefix."
    for net in (ipaddress.ip_network("192.168.1.0/24"), ipaddress.ip_network("2001:db8::/32")):
        v = IpValue.from_ip(net)
        assert v.net == net
        assert v.prefix == net.prefixlen


def test_from_ip_string_prefix_quirk():
    "Strings parse as interfaces (bare → /128); address objects keep None."
    assert IpValue.from_ip("fe80::1").prefix == 128
    assert IpValue.from_ip(ipaddress.IPv6Address("fe80::1")).prefix is None


def test_from_ip_int_bytes():
    "ints and bytes are taken as already-mapped 128-bit values."
    raw = bytes.fromhex("20010db8000000000000000000000001")
    assert IpValue.from_ip(int.from_bytes(raw, "big")).addr == raw
    assert IpValue.from_ip(raw).addr == raw
    assert IpValue.from_ip(raw).prefix is None


def test_eq_hash():
    "Equal values compare and hash equal; prefix distinguishes them."
    a = IpValue.from_ip("10.0.0.5/24")
    b = IpValue.from_ip("10.0.0.5/24")
    c = IpValue.from_ip("10.0.0.5/25")
    assert a == b
    assert hash(a) == hash(b)
    assert a != c
    assert a != "not-an-ip"


def test_link_local_from_mac():
    "EUI-64 link-local derivation, including locally-administered MACs."
    assert link_local_from_mac(EUI("00:11:22:33:44:55")) == ipaddress.IPv6Address(
        "fe80::211:22ff:fe33:4455"
    )
    # U/L bit already set on the MAC → flipped to 0 in the IID.
    assert link_local_from_mac(EUI("02:11:22:33:44:55")) == ipaddress.IPv6Address(
        "fe80::11:22ff:fe33:4455"
    )


def test_is_mac_link_local():
    "Detect EUI-64-from-48-bit-MAC link-local addresses structurally."
    cases = [
        ("fe80::211:22ff:fe33:4455", True),
        ("fe80::11:22ff:fe33:4455", True),
        ("fe80::1ff:fe23:4567", True),
        ("fe80::1", False),
        ("2001:db8::1", False),
        ("10.0.0.1", False),
    ]
    for addr, expected in cases:
        assert is_mac_link_local(addr) is expected, addr
    # An IPv6Address object is accepted too.
    assert is_mac_link_local(ipaddress.IPv6Address("fe80::211:22ff:fe33:4455")) is True


def test_mac_addr_accepts_eui_str_bytes(eng):
    ":class:`MacAddr` binds EUI, str, int, and bytes identically."
    inputs = [
        EUI("00:11:22:33:44:55"),
        "00:11:22:33:44:55",
        0x001122334455,
        EUI("00:11:22:33:44:55").packed,
    ]
    with Session(eng) as sess:
        for mac in inputs:
            r = _Row()
            r.ip = IpValue.from_ip("10.0.0.5/24")
            r.mac = mac
            sess.add(r)
        sess.commit()
        got = sess.scalars(select(_Row).order_by(_Row.id)).all()
    for row in got:
        assert row.mac == EUI("00:11:22:33:44:55")
        assert row.mac.packed == EUI("00:11:22:33:44:55").packed
        assert row.ip == IpValue.from_ip("10.0.0.5/24")


def test_orm_roundtrip(eng):
    "The composite and MAC type survive a SQLite round-trip."
    with Session(eng) as sess:
        rows = [
            ("10.0.0.5/24", EUI("00:11:22:33:44:55")),
            (ipaddress.IPv6Address("2001:db8::1"), None),
            (ipaddress.ip_network("192.168.1.0/24"), None),
        ]
        for ip, mac in rows:
            r = _Row()
            r.ip = IpValue.from_ip(ip)
            r.mac = mac
            sess.add(r)
        sess.commit()
        got = sess.scalars(select(_Row).order_by(_Row.id)).all()
    assert got[0].ip == IpValue.from_ip("10.0.0.5/24")
    assert got[0].ip.net == ipaddress.ip_network("10.0.0.0/24")
    assert got[0].mac == EUI("00:11:22:33:44:55")
    assert link_local_from_mac(got[0].mac) == ipaddress.IPv6Address("fe80::211:22ff:fe33:4455")
    assert got[1].ip == IpValue.from_ip(ipaddress.IPv6Address("2001:db8::1"))
    assert got[1].mac is None
    assert got[2].ip.net == ipaddress.ip_network("192.168.1.0/24")
