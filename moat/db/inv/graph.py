"""Reachability walk over the inventory graph.

Answers *"given this host/interface, what is physically connected to
it?"*: a breadth-first walk over cables and host bodies, yielding every
reached node together with the hop chain that led there. The successor
of :meth:`moat.kv.inv.model.Host.connected_hosts`, expressed as a pure
walker over the SQL model — no DistKV traversal machinery, no implicit
cache warming; the session is an explicit parameter (mirroring
:mod:`moat.db.inv.resolve` and :mod:`moat.db.inv.vlans`).

Traversal model
===============

Nodes alternate between interfaces and hosts. Edges, all bidirectional:

* an :class:`~moat.db.inv.model.Interface` is joined to its cable partner
  by the :class:`~moat.db.inv.model.Cable` between them;
* an interface is joined to the :class:`~moat.db.inv.model.Host` owning
  it;
* a host is joined to each of its interfaces.

Decision D1 of the migration plan dissolves the old ``Wire`` class: a
wire is a host whose Thing type is ``wire`` with exactly two interfaces
``a`` / ``b``. Passing through a wire is therefore two ordinary host
hops — interface → wire host → other interface — with no special case,
exactly as the plan prescribes.

Virtual networks
================

The DistKV walker stepped sideways into a virtual network's member
enumeration whenever it met a port on one, relying on subtree mechanics.
Here the virtual network is an *edge source* instead: every interface
carrying an address inside a :attr:`Network` with ``virt=True`` is
adjacent to every other such interface. The closure is the same — both
spellings say "these machines share a medium without a cable" — but the
SQL form derives the member set from the interfaces' own addresses
rather than a side-channel membership list.

Ordering and bookkeeping
========================

Discovery is strictly breadth-first, matching the old walker's ``deque``
discipline. Bookkeeping is by node identity (interface or host ``id``),
so diamond topologies terminate: a node reached twice is yielded once,
via whichever shorter hop chain found it first.

Consumers receive ``(node, hops)`` pairs, where ``hops`` is the tuple of
nodes traversed from the origin (exclusive of the yielded node itself).
That is enough to rebuild a route for printing or to filter by
intermediate hops.

Loading strategy
================

The whole inventory is small and the walk touches a sizeable fraction of
it, so the walker bulk-loads interfaces, cables, and virtual-network
memberships up front and walks the in-memory adjacency — the same
discipline as :mod:`moat.db.inv.vlans`.
"""

from __future__ import annotations

from sqlalchemy import select

from moat.db.inv.model import Address, Cable, Host, Interface, Network

from collections import deque
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

__all__ = ["GraphNode", "HopChain", "WalkerSession", "connected_hosts"]

#: A node of the walk: an interface or a host.
GraphNode = Interface | Host
#: The nodes traversed from the origin to a reached node (origin exclusive).
HopChain = tuple[GraphNode, ...]


@runtime_checkable
class WalkerSession(Protocol):
    """The slice of a session the walker needs.

    Structurally identical to
    :class:`moat.db.inv.resolve.ResolverSession`: anything whose
    ``execute(stmt)`` yields a result with ``scalars()``. Declared
    narrowly so background sweeps and report jobs can supply their own
    session and drive the walker independently of ambient globals.
    """

    def execute(self, statement: Any) -> Any:
        """Execute a SQLAlchemy statement, returning a result with ``scalars()``."""
        ...


def connected_hosts(
    sess: WalkerSession,
    origin: GraphNode,
) -> Iterator[tuple[GraphNode, HopChain]]:
    """Walk the inventory graph outward from ``origin``, breadth-first.

    Yields every reached node — interfaces and hosts alike — together
    with the hop chain leading to it. The origin itself is yielded first,
    with an empty chain. A node reached along several equally-short routes
    is yielded once (diamonds terminate); wires contribute no special
    case (decision D1): passing through one is two ordinary host hops.

    Args:
        sess: the database session — anything satisfying
            :class:`WalkerSession` (the CLI's :class:`~moat.db.util.Mgr`
            or a bare :class:`sqlalchemy.orm.Session`).
        origin: the :class:`~moat.db.inv.model.Interface` or
            :class:`~moat.db.inv.model.Host` to start from. It must be
            persistent in ``sess`` (matched by ``id`` against the loaded
            inventory).

    Returns:
        An iterator of ``(node, hops)`` pairs, ``hops`` being the tuple of
        intermediate nodes from the origin to ``node`` (exclusive of both).
        Empty when the origin is unknown to the session.
    """
    # Bulk-load the inventory once: interfaces by id, host rosters, cable
    # partnerships, hosts, and the interfaces seated on each virtual
    # network. Walking the in-memory adjacency avoids per-relationship
    # lazy loads and keeps the session the sole driver of the work.
    ifaces: dict[int, Interface] = {}
    host_ifaces: dict[int, list[Interface]] = {}
    for i in sess.execute(select(Interface)).scalars():
        ifaces[i.id] = i
        host_ifaces.setdefault(i.host_id, []).append(i)

    hosts: dict[int, Host] = {h.id: h for h in sess.execute(select(Host)).scalars()}

    partners: dict[int, int] = {}
    for c in sess.execute(select(Cable)).scalars():
        partners[c.iface_a_id] = c.iface_b_id
        partners[c.iface_b_id] = c.iface_a_id

    virt_members: dict[int, list[Interface]] = {}
    iface_nets: dict[int, list[Network]] = {}
    nets: dict[int, Network] = {
        n.id: n for n in sess.execute(select(Network).where(Network.virt)).scalars()
    }
    if nets:
        # Interface → virtual-network membership, from the interfaces'
        # own address rows (derived addresses are materialised by the
        # model's flush listener, so scanning them suffices).
        for a in sess.execute(select(Address)).scalars():
            if a.prefix is None:
                continue
            addr_int = int.from_bytes(a.addr, "big")
            for net in nets.values():
                net_int = int.from_bytes(net.addr, "big")
                mask = (1 << (128 - net.prefix)) - 1 if net.prefix < 128 else 0
                if (addr_int & ~mask) == (net_int & ~mask):
                    iface_nets.setdefault(a.interface_id, []).append(net)
                    virt_members.setdefault(net.id, []).append(ifaces[a.interface_id])

    # Resolve the origin to a loaded node; a transient or foreign object
    # yields nothing.
    start = _resolve_origin(origin, ifaces, hosts)
    if start is None:
        return

    # Breadth-first, bookkeeping by node identity so diamonds terminate.
    seen: set[tuple[str, int]] = {(start.__class__.__name__, start.id)}
    todo: deque[tuple[GraphNode, HopChain]] = deque([(start, ())])

    while todo:
        node, hops = todo.popleft()
        yield node, hops

        for nxt in _neighbours(
            node, ifaces, hosts, host_ifaces, partners, virt_members, iface_nets
        ):
            key = (nxt.__class__.__name__, nxt.id)
            if key in seen:
                continue
            seen.add(key)
            todo.append((nxt, (*hops, node)))


def _resolve_origin(
    origin: GraphNode, ifaces: dict[int, Interface], hosts: dict[int, Host]
) -> GraphNode | None:
    """Map ``origin`` onto the bulk-loaded inventory.

    Returns ``None`` for a transient or foreign object — a walk from an
    unknown node yields nothing.
    """
    if isinstance(origin, Interface):
        return ifaces.get(origin.id)
    if isinstance(origin, Host):
        return hosts.get(origin.id)
    raise TypeError(f"Not an inventory node: {origin!r}")


def _neighbours(
    node: GraphNode,
    ifaces: dict[int, Interface],
    hosts: dict[int, Host],
    host_ifaces: dict[int, list[Interface]],
    partners: dict[int, int],
    virt_members: dict[int, list[Interface]],
    iface_nets: dict[int, list[Network]],
) -> Iterable[GraphNode]:
    """Yield the nodes adjacent to ``node``.

    * an interface → its cable partner, its owning host, and the other
      members of every virtual network it sits on;
    * a host → its interfaces.
    """
    if isinstance(node, Interface):
        p = partners.get(node.id)
        if p is not None:
            yield ifaces[p]
        h = hosts.get(node.host_id)
        if h is not None:
            yield h
        for net in iface_nets.get(node.id, ()):
            for member in virt_members.get(net.id, ()):
                if member.id != node.id:
                    yield member
    else:
        yield from host_ifaces.get(node.id, ())
