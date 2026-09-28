"""Forward reachability: interface → the VLANs it is exposed to.

Answers the operational question *"if I plug into this port, which VLANs am
I dragged into?"* — the fact set a router's per-port auto-configuration
reads to decide what to tag, what to leave untagged, and what to block.

The primitive is :func:`connected_vlans`; the session is an explicit
parameter so background sweeps and report jobs can drive the collector
independently of the CLI's ambient session (mirroring the discipline of
:mod:`moat.db.inv.resolve`).

Traversal model
===============

Edges of the graph, all bidirectional:

* an :class:`~moat.db.inv.model.Interface` is joined to its cable partner
  by the :class:`~moat.db.inv.model.Cable` between them;
* an interface is joined to every *other* interface of the same
  :class:`~moat.db.inv.model.Host` — entering a host through one interface
  lets you leave through any of its siblings.

Decision D1 of the migration plan dissolves the old ``Wire`` class: a wire
is a host whose Thing type is ``wire`` with exactly two interfaces ``a`` /
``b`` and no VLAN of its own. Passing through a wire is therefore just two
ordinary host hops — no special case, exactly as the plan prescribes.

Harvesting rule
===============

At every interface the walk reaches, the interface's *own* VLAN
(:attr:`Interface.vlan`) is collected. That stamp dominates: in the new
schema an interface points at its VLAN directly, so there is no longer a
separate "the VLAN implied by the interface's network" path to arbitrate
against — the stamp *is* the only determination. An interface with no VLAN
(a wire endpoint, or an unconfigured port) contributes nothing yet does not
halt the walk; a wholly disconnected frontier terminates naturally.

Asymmetry of the origin
=======================

The queried interface is the port you plug into. Its own VLAN is collected,
and the walk proceeds out of *its* cable — but the origin's *sibling*
interfaces on the same host are deliberately **not** swept. They are
separate segments: standing at port ``sw:1`` tells you nothing about
``sw:2``'s VLAN. Once the walk crosses a cable to a *far* host, that
host's full interface roster is swept (each sibling harvested and its
cable followed), because the far host fans the segment out into further
segments. This mirrors the historical ``moat.kv.inv`` walker and is the
behaviour the downstream template renderer relies on.

Deviation from the historical walker
=====================================

The DistKV walker halted traversal as soon as it hit a port carrying an
explicit ``force_vlan`` stamp (an access port modelled as a leaf). That
early return was coupled to a sibling-subport trunk hack (ports named
``"<vlan>-<suffix>"``) that the migration plan drops entirely
(MIGRATION.md §D6). With the stamp folded into :attr:`Interface.vlan` and
no subport siblings to enumerate, the early return no longer corresponds
to a real configuration statement, so the collector walks *through*
stamped interfaces unconditionally — "continue along reachable neighbours
through cables and wire bodies" is the rule, stated without qualification.
Whether a stamped port ought to be a leaf is a *policy* decision that
belongs in the template consumer, not the collector; the issue expressly
asks that presentation choices not be baked in here.

Loading strategy
================

The whole inventory is small and the walk touches a sizeable fraction of
it, so the collector loads every interface, cable, and VLAN up front in
three bulk ``SELECT`` s and walks the resulting in-memory adjacency. This
keeps the session the genuine driver of the work (no lazy per-relationship
loads), suits the future "cheap periodic sweep" reuse the issue foresees,
and makes cycle protection a plain set of integer ids.

Returned shape
==============

A :class:`set` of :class:`~moat.db.inv.model.Vlan` rows. Sets give
membership tests for aggregate tallies, ``len()`` for counting distinct
VLANs, and iteration for per-port detail feeds, all without imposing an
ordering (the issue asks that sorting/labelling be left to callers).
Equality is order-independent, so repeated evaluation on unchanged data
compares stable.
"""

from __future__ import annotations

from sqlalchemy import select

from moat.db.inv.model import Cable, Interface, Vlan

from typing import Any, Protocol, runtime_checkable

__all__ = ["CollectorSession", "connected_vlans"]


@runtime_checkable
class CollectorSession(Protocol):
    """The slice of a session the collector needs.

    Structurally identical to :class:`moat.db.inv.resolve.ResolverSession`:
    anything whose ``execute(stmt)`` yields a result with ``scalars()``.
    Declared narrowly (rather than pinning the CLI's :class:`~moat.db.util.Mgr`
    or a bare :class:`sqlalchemy.orm.Session`) so background sweeps and
    report jobs can supply their own session and drive the collector
    independently of ambient globals.
    """

    def execute(self, statement: Any) -> Any:
        """Execute a SQLAlchemy statement, returning a result with ``scalars()``."""
        ...


def connected_vlans(
    sess: CollectorSession,
    iface: Interface,
) -> set[Vlan]:
    """Return the VLANs an interface is exposed to.

    Walks the cable-and-wire-body graph outward from ``iface``, collecting
    every reached interface's own VLAN. The origin's own VLAN is collected
    and its cable followed, but the origin's sibling interfaces on the same
    host are not swept (they are separate segments); a *far* host reached
    across a cable is swept in full — each of its interfaces harvested and
    its cables followed. Wires need no special case (decision D1): a wire
    is a host with two interfaces, so passing through it is two ordinary
    host hops.

    Args:
        sess: the database session — anything satisfying
            :class:`CollectorSession` (the CLI's :class:`~moat.db.util.Mgr`
            or a bare :class:`sqlalchemy.orm.Session`). Taken as an explicit
            parameter so background jobs drive the collector independently
            of ambient globals.
        iface: the :class:`~moat.db.inv.model.Interface` to query. It must
            be persistent in ``sess`` (matched by ``id`` against the loaded
            inventory).

    Returns:
        A :class:`set` of :class:`~moat.db.inv.model.Vlan` rows reachable
        from ``iface``. Empty when the interface is lone and unbonded.
        Order-free, so repeated evaluation on unchanged data compares equal.

    Raises:
        Nothing: a missing cable or VLAN is a terminator, not an error.
    """
    # Bulk-load the inventory once: interfaces by id, cable partnerships,
    # host → interface rosters, and VLAN rows by id. Walking the in-memory
    # adjacency avoids per-relationship lazy loads and keeps the session
    # the sole driver of the work.
    ifaces: dict[int, Interface] = {}
    host_ifaces: dict[int, list[Interface]] = {}
    for i in sess.execute(select(Interface)).scalars():
        ifaces[i.id] = i
        host_ifaces.setdefault(i.host_id, []).append(i)

    partners: dict[int, int] = {}
    for c in sess.execute(select(Cable)).scalars():
        partners[c.iface_a_id] = c.iface_b_id
        partners[c.iface_b_id] = c.iface_a_id

    vlans_by_id: dict[int, Vlan] = {v.id: v for v in sess.execute(select(Vlan)).scalars()}

    start = ifaces.get(iface.id)
    if start is None:
        # The interface is not in the session's inventory (transient, or
        # from another session): nothing to walk.
        return set()

    vlans: set[Vlan] = set()
    seen_ifaces: set[int] = {start.id}
    seen_hosts: set[int] = {start.host_id}

    def harvest(i: Interface) -> None:
        """Collect an interface's own VLAN; the stamp dominates."""
        vid = i.vlan_id
        if vid is not None:
            vlans.add(vlans_by_id[vid])

    def walk(iface_id: int) -> None:
        """Sweep a host reached by crossing a cable into interface ``iface_id``.

        The host of that interface is visited once: each of its interfaces
        is harvested and its cable followed. Cycle protection is by identity
        — interfaces by ``id`` (a cable is never recrossed) and hosts by
        ``id`` (a host is never re-swept, breaking every loop).
        """
        iface = ifaces.get(iface_id)
        if iface is None:
            return
        host_id = iface.host_id
        if host_id in seen_hosts:
            return
        seen_hosts.add(host_id)

        for sibling in host_ifaces.get(host_id, ()):
            if sibling.id in seen_ifaces:
                continue
            seen_ifaces.add(sibling.id)
            harvest(sibling)
            nxt = partners.get(sibling.id)
            if nxt is not None and nxt not in seen_ifaces:
                walk(nxt)

    # Origin: collect its own VLAN and follow its cable. The origin's
    # sibling interfaces are intentionally NOT swept here.
    harvest(start)
    partner_id = partners.get(start.id)
    if partner_id is not None:
        walk(partner_id)

    return vlans
