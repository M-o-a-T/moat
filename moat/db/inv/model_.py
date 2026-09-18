"""Cross-package relationships and ``apply()`` methods for the inventory.

Relationships that would create import cycles (links to
:class:`~moat.db.thing.model.Thing` / :class:`~moat.db.thing.model.ThingTyp`)
are wired here, along with the per-model ``apply()`` methods that resolve
foreign-key names to ORM objects via ``sess.one(Table, name=…)``.
"""

from __future__ import annotations

from sqlalchemy.orm import relationship

from moat.util import NotGiven
from moat.db.schema import Base
from moat.db.thing.model import Thing, ThingTyp
from moat.db.util import session

from .ip import IpValue
from .model import Address, Cable, Host, HostGroup, Interface, Network, Vlan

from typing import Any, cast

# ---------------------------------------------------------------------------
# Cross-package relationships
# ---------------------------------------------------------------------------

cast(Any, Host).thing = relationship(Thing, back_populates="host")
cast(Any, Thing).host = relationship(
    "moat.db.inv.model.Host", back_populates="thing", uselist=False
)


# ---------------------------------------------------------------------------
# Apply methods
# ---------------------------------------------------------------------------


def vlan_apply(self, **kw) -> None:
    """Apply mutable VLAN properties.

    Args:
        **kw: Scalar columns (``tag``, ``name``, ``desc``, ``wlan``,
            ``passwd``) forwarded to :meth:`Base.apply`.
    """
    Base.apply(self, **kw)


Vlan.apply = cast(Any, vlan_apply)


def network_apply(self, vlan=NotGiven, subnet=NotGiven, **kw) -> None:
    """Apply mutable network properties.

    Args:
        vlan: Name of the :class:`Vlan` this network rides on. Required
            for a new network; cannot be cleared.
        subnet: An IP network (``IPv4Network`` / ``IPv6Network`` /
            ``str``) whose address and prefix populate ``addr`` and
            ``prefix``. Stored via :meth:`IpValue.from_ip`.
        **kw: Scalar columns (``name``, ``shift``, ``desc``, ``virt``,
            ``dhcp_first``, ``dhcp_count``) forwarded to
            :meth:`Base.apply`.
    """
    sess = session.get()
    with sess.no_autoflush:
        Base.apply(self, **kw)

        if vlan is not NotGiven:
            if vlan is None:
                raise ValueError("Networks need a VLAN")
            self.vlan = sess.one(Vlan, name=vlan)
        elif self.vlan is None:
            raise ValueError("New networks need a VLAN")

        if subnet is not NotGiven:
            if subnet is None:
                raise ValueError("Networks need a subnet")
            sv = IpValue.from_ip(subnet)
            self.addr = sv.addr
            self.prefix = sv.prefix


Network.apply = cast(Any, network_apply)


def host_apply(self, name=NotGiven, thingtyp=NotGiven, descr=NotGiven, **kw) -> None:
    """Apply mutable host properties.

    Creates the underlying :class:`Thing` if the host is new. The short
    name lives on ``thing.name`` (D4); ``domain`` is the FQDN.

    Args:
        name: Short name for the underlying Thing (≤40 chars, globally
            unique). Required for a new host.
        thingtyp: Thing type name (defaults to ``"host"`` for new hosts;
            ``"wire"`` for wires). Immutable once set.
        descr: Description forwarded to ``thing.descr``.
        **kw: Scalar columns (``domain``, ``loc``) forwarded to
            :meth:`Base.apply`.
    """
    sess = session.get()
    with sess.no_autoflush:
        Base.apply(self, **kw)

        if self.thing is None:
            if name is NotGiven or name is None:
                raise ValueError("New hosts need a name")
            ttyp_name: str = "host" if thingtyp is NotGiven else thingtyp
            if ttyp_name is None:
                raise ValueError("Hosts need a thing type")
            ttyp = sess.one(ThingTyp, name=ttyp_name)
            if ttyp.abstract:
                raise ValueError("Hosts need a non-abstract thing type")
            thing = Thing(name=name, thingtyp=ttyp)
            if descr is not NotGiven and descr is not None:
                thing.descr = descr
            sess.add(thing)
            self.thing = thing
        else:
            if name is not NotGiven and name is not None:
                self.thing.name = name
            if descr is not NotGiven and descr is not None:
                self.thing.descr = descr
            if thingtyp is not NotGiven and thingtyp is not None:
                if self.thing.thingtyp is None:
                    self.thing.thingtyp = sess.one(ThingTyp, name=thingtyp)
                elif self.thing.thingtyp.name != thingtyp:
                    raise ValueError("Thing types cannot be changed")


Host.apply = cast(Any, host_apply)


def interface_apply(
    self,
    host=NotGiven,
    vlan=NotGiven,
    mac=NotGiven,
    seqnum=NotGiven,
    **kw,
) -> None:
    """Apply mutable interface properties.

    Args:
        host: Domain name (FQDN) of the :class:`Host` this interface
            belongs to. Required for a new interface; cannot be cleared.
        vlan: Name of the :class:`Vlan` this interface plugs into, or
            ``None`` / ``"-"`` to clear (for wire a/b endpoints).
        mac: MAC address (``netaddr.EUI``, ``str``, ``int``, or 6
            ``bytes``) or ``None`` to clear.
        seqnum: The host offset within the VLAN, or ``None`` to clear.
        **kw: Scalar columns (``name``, ``desc``) forwarded to
            :meth:`Base.apply`.
    """
    sess = session.get()
    with sess.no_autoflush:
        Base.apply(self, **kw)

        if host is not NotGiven:
            if host is None:
                raise ValueError("Interfaces need a host")
            self.host = sess.one(Host, domain=host)
        elif self.host is None:
            raise ValueError("New interfaces need a host")

        if vlan is NotGiven:
            pass
        elif vlan is None or vlan == "-":
            self.vlan = None
        else:
            self.vlan = sess.one(Vlan, name=vlan)

        if mac is not NotGiven:
            if mac is None or mac == "-":
                self.mac = None
            else:
                from netaddr import EUI  # noqa: PLC0415

                self.mac = EUI(mac) if not isinstance(mac, EUI) else mac

        if seqnum is not NotGiven:
            self.seqnum = seqnum if seqnum != "-" else None


Interface.apply = cast(Any, interface_apply)


def address_apply(self, _interface=NotGiven, ip=NotGiven, **kw) -> None:
    """Apply mutable address properties.

    Args:
        interface: Not used directly — the interface is set by the
            caller (usually via ``interface.addresses.add(...)``).
            Accepted for symmetry.
        ip: An IP address/interface/network/string whose address and
            prefix populate ``addr`` and ``prefix``. Stored via
            :meth:`IpValue.from_ip`.
        **kw: Forwarded to :meth:`Base.apply`.
    """
    sess = session.get()
    with sess.no_autoflush:
        Base.apply(self, **kw)

        if ip is not NotGiven:
            if ip is None:
                raise ValueError("Addresses need an IP")
            sv = IpValue.from_ip(ip)
            self.addr = sv.addr
            self.prefix = sv.prefix


Address.apply = cast(Any, address_apply)


def cable_apply(self, iface_a=NotGiven, iface_b=NotGiven, **kw) -> None:
    """Apply mutable cable properties.

    Args:
        iface_a: Spec string ``"HOST:IFACE"`` for the A endpoint.
        iface_b: Spec string ``"HOST:IFACE"`` for the B endpoint.
        **kw: Forwarded to :meth:`Base.apply`.
    """
    sess = session.get()
    with sess.no_autoflush:
        Base.apply(self, **kw)

        if iface_a is not NotGiven:
            if iface_a is None:
                raise ValueError("Cables need an A endpoint")
            self.iface_a = _resolve_iface(sess, iface_a)

        if iface_b is not NotGiven:
            if iface_b is None:
                raise ValueError("Cables need a B endpoint")
            self.iface_b = _resolve_iface(sess, iface_b)


Cable.apply = cast(Any, cable_apply)


def group_apply(self, **kw) -> None:
    """Apply mutable group properties.

    Args:
        **kw: Scalar columns (``name``, ``desc``) forwarded to
            :meth:`Base.apply`.
    """
    Base.apply(self, **kw)


HostGroup.apply = cast(Any, group_apply)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_iface(sess, spec: str) -> Interface:
    """Resolve a ``"DOMAIN:IFACE"`` spec to an :class:`Interface` row.

    The interface name ``"."`` maps to the empty-string interface
    (the former direct attachment).
    """
    try:
        domain, iname = spec.split(":", 1)
    except ValueError:
        raise ValueError(f"Bad interface spec {spec!r}; use 'domain:iface'.") from None

    if iname == ".":
        iname = ""

    host = sess.one(Host, domain=domain)
    return sess.one(Interface, host=host, name=iname)
