"""
IP-address and MAC types for the MoaT inventory database.

Models in :mod:`moat.db.inv.model` store every network and interface
address as a ``BINARY(16)`` address plus an optional ``SMALLINT`` prefix,
with IPv4 carried in the IPv4-mapped IPv6 form ``::ffff:a.b.c.d``. This
module supplies the composite value class and converters that realise
that encoding, a MAC column type, and the helpers for deriving and
detecting EUI-64 link-local addresses.

:class:`IpValue` is wired to a model's ``addr``/``prefix`` columns with
:func:`sqlalchemy.orm.composite` in :mod:`moat.db.inv.model`.
"""

from __future__ import annotations

import ipaddress

from netaddr import EUI
from sqlalchemy import LargeBinary, TypeDecorator

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.engine import Dialect

__all__ = ["IpLike", "IpValue", "MacAddr", "is_mac_link_local", "link_local_from_mac"]

_LINK_LOCAL: ipaddress.IPv6Network = ipaddress.IPv6Network("fe80::/10")

#: A bare IP address (no netmask).
IpAddr = ipaddress.IPv4Address | ipaddress.IPv6Address
#: A host address with a netmask.
IpIface = ipaddress.IPv4Interface | ipaddress.IPv6Interface
#: A network.
IpNet = ipaddress.IPv4Network | ipaddress.IPv6Network
#: Either a bare address or a host interface.
IpView = IpAddr | IpIface
#: Anything :meth:`IpValue.from_ip` accepts.
IpLike = IpView | IpNet | str | int | bytes | bytearray


def _ip_to_int(addr: IpAddr) -> int:
    """Map an address to its 128-bit IPv6-mapped integer.

    IPv4 addresses are encoded as ``::ffff:a.b.c.d``
    (``(0xFFFF << 32) | int(addr)``); IPv6 addresses pass through unchanged.
    """
    if isinstance(addr, ipaddress.IPv4Address):
        return (0xFFFF << 32) | int(addr)
    return int(addr)


def _int_to_addr(addr_int: int) -> IpAddr:
    """Recover the address from its 128-bit stored integer.

    IPv4-mapped values (``::ffff:0:0/96``) decode to an
    :class:`~ipaddress.IPv4Address`; everything else to an
    :class:`~ipaddress.IPv6Address`.
    """
    v6 = ipaddress.IPv6Address(addr_int)
    mapped = v6.ipv4_mapped
    if mapped is not None:
        return mapped
    return v6


def _int_to_iface(addr_int: int, prefix: int) -> IpIface:
    """Build a host interface (address + netmask) from stored values."""
    base = _int_to_addr(addr_int)
    if isinstance(base, ipaddress.IPv4Address):
        return ipaddress.IPv4Interface((base, prefix))
    return ipaddress.IPv6Interface((base, prefix))


def _int_to_net(addr_int: int, prefix: int) -> IpNet:
    """Build a network from stored values (host bits masked off)."""
    base = _int_to_addr(addr_int)
    if isinstance(base, ipaddress.IPv4Address):
        return ipaddress.IPv4Network((base, prefix), strict=False)
    return ipaddress.IPv6Network((base, prefix), strict=False)


def _decompose(value: IpLike) -> tuple[int, int | None]:
    """Split an address-like value into its 128-bit integer and prefix.

    Strings are parsed as interfaces, so ``"10.0.0.5/24"`` keeps its
    prefix and a bare ``"fe80::1"`` becomes ``/128``. A bare
    :class:`~ipaddress.IPv4Address`/:class:`~ipaddress.IPv6Address`,
    ``int``, or ``bytes`` yields ``prefix=None``.
    """
    if isinstance(value, ipaddress.IPv4Network | ipaddress.IPv6Network):
        return _ip_to_int(value.network_address), value.prefixlen
    if isinstance(value, ipaddress.IPv4Interface | ipaddress.IPv6Interface):
        return _ip_to_int(value.ip), value.network.prefixlen
    if isinstance(value, ipaddress.IPv4Address | ipaddress.IPv6Address):
        return _ip_to_int(value), None
    if isinstance(value, str):
        ifc = ipaddress.ip_interface(value)
        return _ip_to_int(ifc.ip), ifc.network.prefixlen
    if isinstance(value, int):
        return value, None
    if isinstance(value, bytes | bytearray):
        return int.from_bytes(value, "big"), None
    raise TypeError(f"Not an address: {type(value).__name__}")


class IpValue:
    """A 16-byte IPv6-mapped address paired with an optional prefix.

    Attributes:
        addr: 16 big-endian bytes (the 128-bit integer from
            :func:`_ip_to_int`).
        prefix: the netmask length (``0``–``128``), or ``None`` for a
            bare address with no netmask.

    Map this to a model's ``addr``/``prefix`` columns with
    :func:`sqlalchemy.orm.composite`::

        ip: Mapped[IpValue] = composite(IpValue, "addr", "prefix")

    The host view is :attr:`ip`; the network view is :attr:`net`.
    """

    addr: bytes
    prefix: int | None

    def __init__(self, addr: bytes, prefix: int | None = None) -> None:
        self.addr = addr
        self.prefix = prefix

    def __composite_values__(self) -> tuple[bytes, int | None]:
        """Return the column values for SQLAlchemy."""
        return self.addr, self.prefix

    @property
    def ip(self) -> IpView:
        """The address as a host object.

        A set prefix yields an :class:`~ipaddress.IPv4Interface` /
        :class:`~ipaddress.IPv6Interface`; a ``None`` prefix yields a bare
        :class:`~ipaddress.IPv4Address` / :class:`~ipaddress.IPv6Address`.
        """
        addr_int = int.from_bytes(self.addr, "big")
        if self.prefix is None:
            return _int_to_addr(addr_int)
        return _int_to_iface(addr_int, self.prefix)

    @property
    def net(self) -> IpNet:
        """The address as a network (requires a prefix)."""
        if self.prefix is None:
            raise ValueError("IpValue has no prefix")
        return _int_to_net(int.from_bytes(self.addr, "big"), self.prefix)

    @classmethod
    def from_ip(cls, value: IpLike) -> IpValue:
        """Build an :class:`IpValue` from an address-like value.

        Args:
            value: an address, interface, or network object; a string
                (parsed as an interface); or a 128-bit ``int`` / 4-or-16
                byte ``bytes`` (taken as already IPv6-mapped, prefix
                ``None``).
        """
        addr_int, prefix = _decompose(value)
        return cls(addr_int.to_bytes(16, "big"), prefix)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, IpValue):
            return False
        return self.addr == other.addr and self.prefix == other.prefix

    def __hash__(self) -> int:
        return hash((self.addr, self.prefix))

    def __repr__(self) -> str:
        return f"IpValue({self.ip!r})"

    def __str__(self) -> str:
        return str(self.ip)


class MacAddr(TypeDecorator):
    """Column type for a 48-bit MAC address stored as ``BINARY(6)``.

    The Python-side value is a :class:`netaddr.EUI`. Binding accepts an
    :class:`~netaddr.EUI`, a string, an ``int``, or 6 ``bytes``; loading
    returns an :class:`~netaddr.EUI` (or ``None``).
    """

    impl = LargeBinary(6)
    cache_ok = True

    def process_bind_param(
        self, value: EUI | str | int | bytes | bytearray | None, dialect: Dialect
    ) -> bytes | None:
        """Convert a MAC to its 6 stored bytes."""
        dialect  # noqa:B018
        if value is None:
            return None
        if isinstance(value, bytes | bytearray):
            return bytes(value)
        return EUI(value).packed

    def process_result_value(self, value: bytes | None, dialect: Dialect) -> EUI | None:
        """Reconstruct an :class:`~netaddr.EUI` from stored bytes."""
        dialect  # noqa:B018
        if value is None:
            return None
        return EUI(int.from_bytes(value, "big"))


def link_local_from_mac(mac: EUI) -> ipaddress.IPv6Address:
    """Return the ``fe80::`` EUI-64 link-local address for ``mac``."""
    return ipaddress.IPv6Address(int(mac.ipv6_link_local()))


def is_mac_link_local(addr: ipaddress.IPv6Address | str) -> bool:
    """Whether ``addr`` is a MAC-derived EUI-64 link-local address.

    Such an address is fully determined by an interface's (already
    unique) MAC, so the ``address`` table rejects it rather than storing a
    redundant row. Detection is structural: the address is in
    ``fe80::/10`` and its 64-bit interface identifier carries the
    ``ff:fe`` infix of a 48-bit-MAC-expanded EUI-64.
    """
    candidate = ipaddress.ip_address(addr) if isinstance(addr, str) else addr
    if not isinstance(candidate, ipaddress.IPv6Address):
        return False
    if candidate not in _LINK_LOCAL:
        return False
    iid = (int(candidate) & 0xFFFFFFFFFFFFFFFF).to_bytes(8, "big")
    return iid[3] == 0xFF and iid[4] == 0xFE
