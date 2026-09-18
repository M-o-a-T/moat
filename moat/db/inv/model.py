"""ORM models for the MoaT network inventory database."""

from __future__ import annotations

import ipaddress

from netaddr import EUI  # noqa: TC002 — needed by SQLAlchemy at import time for Mapped[EUI | None]
from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Table,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import Mapped, Session, composite, mapped_column, relationship

from moat.db.schema import Base

from .ip import IpValue, MacAddr

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.db.thing.model import Thing

    from typing import Any


# ---------------------------------------------------------------------------
# Association table: host ↔ group (many-to-many)
# ---------------------------------------------------------------------------

host_group = Table(
    "inv_host_group",
    Base.metadata,
    Column(
        "host_id",
        Integer,
        ForeignKey("inv_host.id", name="fk_host_group_host"),
        primary_key=True,
    ),
    Column(
        "group_id",
        Integer,
        ForeignKey("inv_group.id", name="fk_host_group_group"),
        primary_key=True,
    ),
)


# ---------------------------------------------------------------------------
# Vlan
# ---------------------------------------------------------------------------


class Vlan(Base):
    """An 802.1Q VLAN — the layer-2 broadcast domain an interface plugs into.

    Carries zero or more :class:`Network` rows (typically one IPv4 and one
    IPv6) and optional WLAN credentials.
    """

    __tablename__ = "inv_vlan"

    id: Mapped[int] = mapped_column(primary_key=True)
    tag: Mapped[int] = mapped_column(unique=True, comment="802.1Q VLAN tag")
    name: Mapped[str] = mapped_column(unique=True, type_=String(64))
    desc: Mapped[str | None] = mapped_column(type_=String(200), nullable=True)
    wlan: Mapped[str | None] = mapped_column(type_=String(64), nullable=True, comment="WLAN SSID")
    passwd: Mapped[str | None] = mapped_column(
        type_=String(128), nullable=True, comment="WLAN password"
    )

    networks: Mapped[set[Network]] = relationship(back_populates="vlan", passive_deletes=True)
    interfaces: Mapped[set[Interface]] = relationship(back_populates="vlan", passive_deletes=True)

    def dump(self) -> dict[str, Any]:
        """Standard info dump."""
        res = super().dump()
        if self.networks:
            res["nets"] = sorted(n.name for n in self.networks)
        return res


# ---------------------------------------------------------------------------
# Network
# ---------------------------------------------------------------------------


class Network(Base):
    """An IP network riding on a :class:`Vlan`.

    Typically a VLAN carries two networks — one IPv4 and one IPv6. The
    optional ``shift`` enables automatic address derivation from an
    interface's ``seqnum``::

        addr = network.addr + (seqnum << shift)

    Link-local ``fe80::`` addresses are not represented here; they are
    computed from each interface's MAC at runtime.
    """

    __tablename__ = "inv_network"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True, type_=String(64))
    vlan_id: Mapped[int] = mapped_column(
        ForeignKey("inv_vlan.id", name="fk_network_vlan", ondelete="CASCADE"),
        nullable=False,
    )
    addr: Mapped[bytes] = mapped_column(comment="Network address, BINARY(16) big-endian")
    prefix: Mapped[int] = mapped_column(SmallInteger, comment="Netmask length 0–128")
    shift: Mapped[int | None] = mapped_column(
        nullable=True,
        comment="If set, autogen addr = net.addr + (seqnum << shift)",
    )
    desc: Mapped[str | None] = mapped_column(type_=String(200), nullable=True)
    virt: Mapped[bool] = mapped_column(
        default=False, server_default="0", comment="No cable required"
    )
    dhcp_first: Mapped[int | None] = mapped_column(
        nullable=True, comment="First seqnum in the DHCP range"
    )
    dhcp_count: Mapped[int | None] = mapped_column(
        nullable=True, comment="Length of the DHCP range"
    )

    subnet: Mapped[IpValue] = composite(IpValue, "addr", "prefix")

    vlan: Mapped[Vlan] = relationship(back_populates="networks")

    def dump(self) -> dict[str, Any]:
        """Standard info dump."""
        res = super().dump()
        res.pop("addr", None)
        res.pop("prefix", None)
        res["subnet"] = str(self.subnet.net)
        if self.vlan is not None:
            res["vlan"] = self.vlan.name
        return res


# ---------------------------------------------------------------------------
# Host
# ---------------------------------------------------------------------------


class Host(Base):
    """A network host — a :class:`~moat.db.thing.model.Thing` specialised
    with a domain name and location.

    Interfaces, addresses, and group memberships live on this host. A
    wire is simply a host whose Thing type is ``wire``.
    """

    __tablename__ = "inv_host"

    id: Mapped[int] = mapped_column(primary_key=True)
    thing_id: Mapped[int] = mapped_column(
        ForeignKey("thing.id", name="fk_host_thing"),
        unique=True,
        nullable=False,
    )
    domain: Mapped[str] = mapped_column(unique=True, type_=String(255), comment="FQDN")
    loc: Mapped[str | None] = mapped_column(type_=String(200), nullable=True, comment="Location")

    interfaces: Mapped[set[Interface]] = relationship(back_populates="host", passive_deletes=True)
    if TYPE_CHECKING:
        thing: Thing
        groups: set[HostGroup]

    def dump(self) -> dict[str, Any]:
        """Standard info dump."""
        res = super().dump()
        if self.thing is not None:
            res["name"] = self.thing.name
            if self.thing.thingtyp is not None:
                res["typ"] = self.thing.thingtyp.name
        if self.interfaces:
            res["ifaces"] = sorted(i.name for i in self.interfaces)
        if self.groups:
            res["groups"] = sorted(g.name for g in self.groups)
        return res


# ---------------------------------------------------------------------------
# Interface
# ---------------------------------------------------------------------------


class Interface(Base):
    """A network interface belonging to a :class:`Host`.

    The former host-direct attachment is the interface with an empty name
    (spelled ``"."`` on the CLI). An interface plugs into one :class:`Vlan`,
    carries an optional MAC and ``seqnum``, and owns zero or more
    :class:`Address` rows.

    Addresses derived from ``seqnum`` + the VLAN's routable networks are
    regenerated automatically by the ``before_insert``/``before_update``
    listener; link-local addresses are a computed property, never stored.
    """

    __tablename__ = "inv_interface"
    __table_args__ = (
        UniqueConstraint("host_id", "name", name="uq_interface_host_name"),
        UniqueConstraint("vlan_id", "seqnum", name="uq_interface_vlan_seqnum"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    host_id: Mapped[int] = mapped_column(
        ForeignKey("inv_host.id", name="fk_interface_host", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(
        type_=String(64),
        comment='"" = former direct attachment; "." on CLI',
    )
    vlan_id: Mapped[int | None] = mapped_column(
        ForeignKey("inv_vlan.id", name="fk_interface_vlan"),
        nullable=True,
        comment="The VLAN this interface is on (NULL for wire a/b)",
    )
    mac: Mapped[EUI | None] = mapped_column(
        MacAddr, nullable=True, comment="MAC address → netaddr.EUI"
    )
    seqnum: Mapped[int | None] = mapped_column(
        nullable=True,
        comment="Host offset within the VLAN; NULL for wires/unassigned",
    )
    desc: Mapped[str | None] = mapped_column(type_=String(200), nullable=True)

    host: Mapped[Host] = relationship(back_populates="interfaces")
    vlan: Mapped[Vlan | None] = relationship(back_populates="interfaces")
    addresses: Mapped[set[Address]] = relationship(
        back_populates="interface", passive_deletes=True
    )
    if TYPE_CHECKING:
        cable_a: set[Cable]
        cable_b: set[Cable]

    @property
    def link_local(self) -> ipaddress.IPv6Address | None:
        """The EUI-64 link-local address derived from this interface's MAC.

        Returns ``None`` when no MAC is set. The address is computed at
        runtime and never stored as an :class:`Address` row.
        """
        from .ip import link_local_from_mac  # noqa: PLC0415

        if self.mac is None:
            return None
        return link_local_from_mac(self.mac)

    def dump(self) -> dict[str, Any]:
        """Standard info dump."""
        res = super().dump()
        res.pop("mac", None)
        if self.mac is not None:
            res["mac"] = str(self.mac)
        if self.vlan is not None:
            res["vlan"] = self.vlan.name
        if self.addresses:
            res["addrs"] = sorted(str(a.ip.ip) for a in self.addresses)
        if self.link_local is not None:
            res["link_local"] = str(self.link_local)
        return res


# ---------------------------------------------------------------------------
# Address
# ---------------------------------------------------------------------------


class Address(Base):
    """An IP address assigned to an :class:`Interface`.

    The L3 layer: an address hangs off an interface and may belong to any
    network (or none). MAC-derived ``fe80::`` link-local addresses are
    rejected by the validator — they are computed from the interface's MAC
    at runtime instead.
    """

    __tablename__ = "inv_address"

    id: Mapped[int] = mapped_column(primary_key=True)
    interface_id: Mapped[int] = mapped_column(
        ForeignKey("inv_interface.id", name="fk_address_interface", ondelete="CASCADE"),
        nullable=False,
    )
    addr: Mapped[bytes] = mapped_column(unique=True, comment="IP address, BINARY(16) big-endian")
    prefix: Mapped[int | None] = mapped_column(
        SmallInteger, nullable=True, comment="Netmask; NULL for floating/anycast"
    )

    ip: Mapped[IpValue] = composite(IpValue, "addr", "prefix")

    interface: Mapped[Interface] = relationship(back_populates="addresses")

    def dump(self) -> dict[str, Any]:
        """Standard info dump."""
        res = super().dump()
        res.pop("addr", None)
        res.pop("prefix", None)
        res["ip"] = str(self.ip.ip)
        return res


# ---------------------------------------------------------------------------
# Cable
# ---------------------------------------------------------------------------


class Cable(Base):
    """A physical cable linking two :class:`Interface` endpoints.

    Cables are anonymous link records (not Things). Each interface is in
    at most one cable.
    """

    __tablename__ = "inv_cable"
    __table_args__ = (
        CheckConstraint("iface_a_id <> iface_b_id", name="ck_cable_distinct"),
        UniqueConstraint("iface_a_id", name="uq_cable_a"),
        UniqueConstraint("iface_b_id", name="uq_cable_b"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    iface_a_id: Mapped[int] = mapped_column(
        ForeignKey("inv_interface.id", name="fk_cable_iface_a", ondelete="CASCADE"),
        nullable=False,
    )
    iface_b_id: Mapped[int] = mapped_column(
        ForeignKey("inv_interface.id", name="fk_cable_iface_b", ondelete="CASCADE"),
        nullable=False,
    )

    iface_a: Mapped[Interface] = relationship(
        foreign_keys="Cable.iface_a_id",
        back_populates="cable_a",
    )
    iface_b: Mapped[Interface] = relationship(
        foreign_keys="Cable.iface_b_id",
        back_populates="cable_b",
    )


# ---------------------------------------------------------------------------
# HostGroup
# ---------------------------------------------------------------------------


class HostGroup(Base):
    """A named group of hosts (e.g. "routers", "servers").

    Membership is via the :data:`host_group` association table.
    """

    __tablename__ = "inv_group"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True, type_=String(64))
    desc: Mapped[str | None] = mapped_column(type_=String(200), nullable=True)

    hosts: Mapped[set[Host]] = relationship(secondary=host_group, back_populates="groups")

    def dump(self) -> dict[str, Any]:
        """Standard info dump."""
        res = super().dump()
        if self.hosts:
            res["hosts"] = sorted(h.thing.name for h in self.hosts)
        return res


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------


@event.listens_for(Address, "before_insert")
@event.listens_for(Address, "before_update")
def validate_address_not_mac_link_local(mapper, connection, model):
    """Reject MAC-derived EUI-64 link-local addresses.

    Such addresses are fully determined by the interface's already-unique
    MAC and are exposed as a computed property; storing them would be
    redundant. Non-EUI-64 ``fe80::`` addresses are still allowed.
    """
    mapper, connection  # noqa: B018
    from .ip import is_mac_link_local  # noqa: PLC0415

    addr_val = model.ip
    if addr_val is None:
        return
    ip_obj = addr_val.ip
    if isinstance(ip_obj, ipaddress.IPv6Address):
        if is_mac_link_local(ip_obj):
            raise ValueError(
                f"Address {ip_obj} is a MAC-derived link-local address; "
                "it is computed from the interface's MAC and must not be stored."
            )


# ---------------------------------------------------------------------------
# Address regeneration — session-level before_flush event
#
# Using before_flush (not before_insert/before_update) because we need to
# safely add/delete Address rows, which is not permitted during the flush
# execution stage.
# ---------------------------------------------------------------------------


def _derive_addresses(iface: Interface) -> dict[bytes, int]:
    """Compute the derived addresses for an interface.

    Returns a mapping of ``addr_bytes → prefix`` for each routable network
    on the interface's VLAN.
    """
    if iface.seqnum is None:
        return {}

    vlan = iface.vlan
    if vlan is None:
        return {}

    derived: dict[bytes, int] = {}
    for net in vlan.networks:
        if net.shift is None:
            continue
        base_int = int.from_bytes(net.addr, "big")
        addr_int = base_int + (iface.seqnum << net.shift)
        addr_bytes = addr_int.to_bytes(16, "big")
        derived[addr_bytes] = net.prefix
    return derived


def _sync_addresses(sess, iface: Interface) -> None:
    """Synchronise an interface's derived address rows.

    Adds missing derived addresses and deletes stale ones (addresses that
    fall inside a VLAN network's range but no longer match the current
    seqnum). Manual addresses outside any routable network are left alone.
    """
    derived = _derive_addresses(iface)
    if not derived and iface.seqnum is None:
        return

    existing: dict[bytes, Address] = {}
    for addr_row in list(iface.addresses):
        existing[addr_row.addr] = addr_row

    # Add missing derived addresses.
    for addr_bytes, prefix in derived.items():
        if addr_bytes not in existing:
            new_addr = Address(interface=iface, addr=addr_bytes, prefix=prefix)
            sess.add(new_addr)
            existing[addr_bytes] = new_addr
        else:
            row = existing[addr_bytes]
            if row.prefix != prefix:
                row.prefix = prefix

    # Delete stale derived addresses.
    if iface.vlan is None:
        return
    for addr_bytes, row in list(existing.items()):
        if addr_bytes in derived:
            continue
        addr_int = int.from_bytes(addr_bytes, "big")
        for net in iface.vlan.networks:
            if net.shift is None:
                continue
            net_base = int.from_bytes(net.addr, "big")
            mask = (1 << (128 - net.prefix)) - 1 if net.prefix < 128 else 0
            if (addr_int & ~mask) == (net_base & ~mask):
                sess.delete(row)
                break


@event.listens_for(Session, "before_flush")
def regenerate_addresses(session_ctx, _instances, items):
    """Regenerate derived address rows for dirty interfaces.

    Triggered before each flush; examines all :class:`Interface` objects
    in the new/dirty sets and synchronises their derived addresses.
    """
    sess = session_ctx
    # Gather all Interface objects that are new or dirty.
    candidates: set[Interface] = set()
    for obj in items or []:
        if isinstance(obj, Interface):
            candidates.add(obj)
    for obj in sess.new:
        if isinstance(obj, Interface):
            candidates.add(obj)
    for obj in sess.dirty:
        if isinstance(obj, Interface):
            candidates.add(obj)
    for obj in candidates:
        _sync_addresses(sess, obj)
