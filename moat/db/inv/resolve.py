"""Reverse lookup: IP address → owning interface and host.

This module implements the point-query resolver that replaces the
arithmetical ``Detour`` formerly used in :mod:`moat.kv.inv`. Where the old
:meth:`HostRoot.by_name` ran ``net.enclosing(the-ip)`` and then subtracted
offsets and probed by-number registries per network, the resolver here is a
straightforward keyed retrieval.

The fast path is ::

    address(addr=given) -> interface -> host -> thing(short name)

without touching networks at all: :attr:`Address.addr` is an indexed
``BINARY(16)`` equal-match column. Providing the *enclosing* network remains
a second, distinct question belonging to whoever wants containment
semantics; the resolver answers ownership only.

Subtleties handled here:

* **v4-mapped inputs** arrive as dotquad-looking strings (``"10.0.0.5"``).
  They are normalised through :meth:`IpValue.from_ip` (the phase-1
  conversion helpers) rather than trusting the textual form, so a bare
  dotted quad, an :class:`~ipaddress.IPv4Address`, an
  :class:`~ipaddress.IPv6Address` holding the mapped form, an ``int``, or
  16 ``bytes`` all collapse to the same stored key.
* **MAC-derived EUI-64 link-local** addresses (``fe80::`` built from a
  48-bit MAC) are *never* stored rows — a deliberate exclusion decided at
  plan time (question 10). A caller handing us such an address must accept
  the slower answer: recompute the derived link-local for every plausible
  candidate interface that has a MAC and compare bit-wise. The two
  behaviours are exposed distinctly via the ``strict`` flag so nobody
  confuses a genuine miss with a derivable-but-absent address.
* **Anycast duplicates** — the same address legitimately on several
  interfaces — cause the resolver to return the *set*; it raises only if
  the *caller* insists on uniqueness (see :func:`resolve_one`).

The primitive is :func:`resolve_interfaces`; :func:`resolve_hosts` and
:func:`resolve_one` are thin conveniences over it. The session is an
explicit parameter so background jobs can drive the resolver independently
rather than binding to ambient globals.
"""

from __future__ import annotations

import ipaddress

from sqlalchemy import select

from moat.db.inv.ip import IpValue, _int_to_addr, is_mac_link_local, link_local_from_mac
from moat.db.inv.model import Address, Interface

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from moat.db.inv.model import Host

__all__ = [
    "AddressNotFound",
    "AmbiguousAddress",
    "ResolverSession",
    "resolve_hosts",
    "resolve_interfaces",
    "resolve_one",
]


@runtime_checkable
class ResolverSession(Protocol):
    """The slice of a session the resolver needs.

    Anything exposing ``execute(stmt)`` whose result offers ``scalars()``
    qualifies — notably both the CLI's :class:`~moat.db.util.Mgr` proxy and
    a bare :class:`sqlalchemy.orm.Session`. Declaring a narrow protocol
    (rather than pinning to one of those) keeps the resolver usable from
    contexts that build their own session: tests, background sweeps, and
    reporting jobs that want to drive the lookup independently of ambient
    globals.
    """

    def execute(self, statement: Any) -> Any:
        """Execute a SQLAlchemy statement, returning a result with ``scalars()``."""
        ...


class AddressNotFound(LookupError):
    """Raised by :func:`resolve_one` when no interface owns the address."""


class AmbiguousAddress(ValueError):
    """Raised by :func:`resolve_one` when several interfaces own the address.

    Carries the offending :class:`~moat.db.inv.model.Interface` rows in
    :attr:`candidates` so the caller can present them.
    """

    def __init__(
        self,
        addr: ipaddress.IPv4Address | ipaddress.IPv6Address,
        candidates: set[Interface],
    ) -> None:
        self.addr = addr
        self.candidates = candidates
        super().__init__(f"Address {addr} is assigned to {len(candidates)} interfaces, not one.")


def _by_stored_address(sess: ResolverSession, key: bytes) -> set[Interface]:
    """Fast path: keyed retrieval on the indexed ``address.addr`` column.

    Joins :class:`Address` → :class:`Interface` and returns the owning
    interface rows. A set is returned even though the current schema marks
    ``addr`` unique, so the resolver is forward-compatible with any future
    relaxation of that constraint for anycast.
    """
    stmt = (
        select(Interface)
        .join(Address, Address.interface_id == Interface.id)
        .where(Address.addr == key)
    )
    return set(sess.execute(stmt).scalars())


def _by_derived_link_local(sess: ResolverSession, target: ipaddress.IPv6Address) -> set[Interface]:
    """Slow path for MAC-derived EUI-64 link-local addresses.

    Such addresses are never stored (question 10); instead every interface
    that carries a MAC has its derived link-local recomputed and compared
    bit-wise to ``target``. Interfaces without a MAC contribute nothing.
    """
    matches: set[Interface] = set()
    stmt = select(Interface).where(Interface.mac.is_not(None))
    for iface in sess.execute(stmt).scalars():
        if iface.mac is None:
            continue  # race-safe guard; the WHERE clause already filters these
        if link_local_from_mac(iface.mac) == target:
            matches.add(iface)
    return matches


def resolve_interfaces(
    sess: ResolverSession,
    addr: ipaddress.IPv4Address | ipaddress.IPv6Address | str | int | bytes | bytearray,
    *,
    strict: bool = False,
) -> set[Interface]:
    """Resolve ``addr`` to the set of interfaces that own it.

    Args:
        sess: the database session — anything satisfying
            :class:`ResolverSession` (the CLI's :class:`~moat.db.util.Mgr`
            or a bare :class:`sqlalchemy.orm.Session`).
        addr: an address-like value — an :class:`~ipaddress.IPv4Address` /
            :class:`~ipaddress.IPv6Address`, a string (dotquad or colon
            form, optionally with a prefix which is ignored for the
            lookup), an ``int``, or 16 ``bytes``. IPv4 is normalised to the
            IPv4-mapped IPv6 form via :meth:`IpValue.from_ip`.
        strict: selects how a MAC-derived EUI-64 link-local address is
            treated. Such an address is deliberately never stored (plan
            question 10), so:

            * ``False`` (default, *best-effort*) — recompute the derived
              link-local for every interface that has a MAC and return
              those whose computed address equals the query. A caller can
              tell a derivable-but-absent address apart from a genuine miss.
            * ``True`` (*strict*) — treat the address like any other
              non-stored value and return an empty set, never falling back
              to derivation. Use this when you want "is this address
              recorded?" semantics.

    Returns:
        The set of :class:`~moat.db.inv.model.Interface` rows owning
        ``addr``. Empty when nothing matches. A set (never a list) so
        anycast duplicates and dual-stack collapses deduplicate naturally.

    Raises:
        ValueError: if ``addr`` cannot be parsed as an IP address.
    """
    ip_val = IpValue.from_ip(addr)
    key = ip_val.addr

    # A MAC-derived link-local is never a stored row. Branch on the strict
    # flag BEFORE hitting the address table so the two behaviours stay
    # distinct: best-effort falls back to derivation, strict does not.
    #
    # The link-local test is done on the raw 128-bit integer (always a valid
    # IPv6Address) rather than on ``ip_val.ip``: the latter rebuilds a host
    # interface from ``(addr, prefix)`` and an IPv4-mapped address carrying
    # an IPv6-style prefix (e.g. ``"::ffff:10.0.0.5"`` → prefix 128) would
    # try to construct an ``IPv4Interface`` with an IPv6-sized mask and
    # raise. Ownership lookup cares only about the address bits, not the
    # prefix, so the integer view is both sufficient and safe.
    ip_obj = ipaddress.IPv6Address(int.from_bytes(key, "big"))
    if is_mac_link_local(ip_obj):
        if strict:
            return set()
        return _by_derived_link_local(sess, ip_obj)

    return _by_stored_address(sess, key)


def resolve_hosts(
    sess: ResolverSession,
    addr: ipaddress.IPv4Address | ipaddress.IPv6Address | str | int | bytes | bytearray,
    *,
    strict: bool = False,
) -> set[Host]:
    """Resolve ``addr`` to the set of hosts that own it.

    Thin convenience over :func:`resolve_interfaces`: collects the
    :class:`~moat.db.inv.model.Host` of each owning interface. Arguments
    and the ``strict`` flag are as for :func:`resolve_interfaces`.
    """
    return {iface.host for iface in resolve_interfaces(sess, addr, strict=strict)}


def resolve_one(
    sess: ResolverSession,
    addr: ipaddress.IPv4Address | ipaddress.IPv6Address | str | int | bytes | bytearray,
    *,
    strict: bool = False,
) -> Interface:
    """Resolve ``addr`` to the single interface that owns it.

    Convenience for callers that insist on uniqueness: returns the one
    owning :class:`~moat.db.inv.model.Interface`, or raises.

    Args:
        sess: the database session.
        addr: an address-like value (see :func:`resolve_interfaces`).
        strict: forwarded to :func:`resolve_interfaces`.

    Returns:
        The sole :class:`~moat.db.inv.model.Interface` owning ``addr``.

    Raises:
        AddressNotFound: no interface owns ``addr``.
        AmbiguousAddress: more than one interface owns ``addr`` (anycast);
            the offenders are available on :attr:`AmbiguousAddress.candidates`.
    """
    found = resolve_interfaces(sess, addr, strict=strict)
    if not found:
        raise AddressNotFound(f"No interface owns {addr!r}.")
    if len(found) > 1:
        raise AmbiguousAddress(
            _int_to_addr(int.from_bytes(IpValue.from_ip(addr).addr, "big")),
            found,
        )
    return next(iter(found))
