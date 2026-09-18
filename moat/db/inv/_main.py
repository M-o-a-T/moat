"""Command-line interface for the MoaT network inventory database.

Commands::

    mt db inv vlan   {add,set,delete,show}
    mt db inv net    {add,set,delete,show}
    mt db inv host   {add,set,delete,show}
    mt db inv host HOST iface {add,set,delete,show,link}
    mt db inv host HOST iface IFACE addr {add,delete,show}
    mt db inv wire   {add,set,delete,show,link}
    mt db inv cable  {show}
    mt db inv group  {add,set,delete,show}

The special interface name ``"."`` selects the empty-named interface
(former direct attachment).
"""

# The main code must not load any sqlalchemy code.
# sqlalchemy might not be present.

from __future__ import annotations

import sys

import asyncclick as click
from sqlalchemy import select

from moat.util import NotGiven, yprint
from moat.db import database
from moat.lib.run import load_subgroup, option_ng

from .model import Address, Cable, Host, HostGroup, Interface, Network, Vlan


@load_subgroup(prefix="moat.db.inv", invoke_without_command=False)
@click.pass_context
def cli(ctx):
    """Network inventory management."""
    obj = ctx.obj
    sess = ctx.with_resource(database(obj.cfg.db))
    ctx.with_resource(sess.begin())
    obj.session = sess


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require(obj, what: str) -> str:
    """Return ``obj.name`` or raise a usage error."""
    name = obj.name
    if name is None:
        raise click.UsageError(f"The {what} needs a name. Use '--name'.")
    return name


def _get_one(obj, model, what: str, **kw):
    """Fetch a single row or raise a usage error."""
    try:
        return obj.session.one(model, **kw)
    except KeyError:
        raise click.UsageError(f"This {what} doesn't exist.") from None


def _absent(obj, model, what: str, **kw) -> None:
    """Raise if a matching row already exists."""
    try:
        obj.session.one(model, **kw)
    except KeyError:
        return
    raise click.UsageError(f"This {what} already exists.") from None


def _norm_iface(name: str) -> str:
    """Map the CLI ``"."`` to the empty interface name."""
    return "" if name == "." else name


# ---------------------------------------------------------------------------
# VLAN
# ---------------------------------------------------------------------------


@cli.group(name="vlan")
@click.option("--tag", "-t", "tag", type=int, help="802.1Q VLAN tag")
@click.pass_obj
def vlan_grp(obj, tag):
    """Manage VLANs."""
    obj.tag = tag


@vlan_grp.command(name="show")
@click.pass_obj
def vlan_show(obj):
    """Show a VLAN or list all VLANs."""
    sess = obj.session
    if obj.tag is None:
        seen = False
        with sess.execute(select(Vlan).order_by(Vlan.tag)) as rs:
            for (v,) in rs:
                seen = True
                print(f"{v.tag}\t{v.name}")
        if not seen:
            print("No VLANs defined yet. Use '--help'?", file=sys.stderr)
    else:
        v = _get_one(obj, Vlan, "VLAN", tag=obj.tag)
        yprint(v.dump())


def vlan_opts(c):
    c = option_ng("--name", "-n", type=str, help="Rename this VLAN")(c)
    c = option_ng("--desc", "-d", type=str, help="Description")(c)
    c = option_ng("--wlan", "-w", type=str, help="WLAN SSID")(c)
    c = option_ng("--passwd", "-p", type=str, help="WLAN password")(c)
    return c


@vlan_grp.command(name="add")
@vlan_opts
@click.pass_obj
def vlan_add(obj, **kw):
    """Add a VLAN."""
    if obj.tag is None:
        raise click.UsageError("The VLAN needs a tag!")
    _absent(obj, Vlan, "VLAN", tag=obj.tag)
    v = Vlan(tag=obj.tag)
    obj.session.add(v)
    v.apply(**kw)


@vlan_grp.command(name="set")
@vlan_opts
@click.pass_obj
def vlan_set(obj, **kw):
    """Modify a VLAN."""
    v = _get_one(obj, Vlan, "VLAN", tag=obj.tag)
    v.apply(**kw)


@vlan_grp.command(name="delete")
@click.pass_obj
def vlan_delete(obj):
    """Delete a VLAN."""
    v = _get_one(obj, Vlan, "VLAN", tag=obj.tag)
    obj.session.delete(v)


# ---------------------------------------------------------------------------
# Network
# ---------------------------------------------------------------------------


@cli.group(name="net")
@click.option("--name", "-n", type=str, help="Network name")
@click.pass_obj
def net_grp(obj, name):
    """Manage IP networks on VLANs."""
    obj.name = name


@net_grp.command(name="show")
@click.pass_obj
def net_show(obj):
    """Show a network or list all networks."""
    sess = obj.session
    if obj.name is None:
        seen = False
        with sess.execute(select(Network).order_by(Network.name)) as rs:
            for (n,) in rs:
                seen = True
                print(n.name, str(n.subnet.net))
        if not seen:
            print("No networks defined yet. Use '--help'?", file=sys.stderr)
    else:
        n = _get_one(obj, Network, "network", name=obj.name)
        yprint(n.dump())


def net_opts(c):
    c = option_ng("--name", "-n", type=str, help="Rename this network")(c)
    c = option_ng("--vlan", "-v", type=str, help="VLAN this network rides on")(c)
    c = option_ng("--subnet", "-s", type=str, help="IP network (e.g. 10.0.0.0/24)")(c)
    c = option_ng("--shift", type=int, help="Shift for seqnum address autogen")(c)
    c = option_ng("--desc", "-d", type=str, help="Description")(c)
    c = option_ng("--virt", "-V", is_flag=True, help="Virtual network (no cable)")(c)
    c = option_ng("--dhcp-first", type=int, help="First seqnum in DHCP range")(c)
    c = option_ng("--dhcp-count", type=int, help="Length of DHCP range")(c)
    return c


@net_grp.command(name="add")
@net_opts
@click.pass_obj
def net_add(obj, **kw):
    """Add a network."""
    name = _require(obj, "network")
    _absent(obj, Network, "network", name=name)
    n = Network(name=name)
    obj.session.add(n)
    n.apply(**kw)


@net_grp.command(name="set")
@net_opts
@click.pass_obj
def net_set(obj, **kw):
    """Modify a network."""
    n = _get_one(obj, Network, "network", name=obj.name)
    n.apply(**kw)


@net_grp.command(name="delete")
@click.pass_obj
def net_delete(obj):
    """Delete a network."""
    n = _get_one(obj, Network, "network", name=obj.name)
    obj.session.delete(n)


# ---------------------------------------------------------------------------
# Host
# ---------------------------------------------------------------------------


@cli.group(name="host")
@click.option("--domain", "-d", type=str, help="FQDN of the host")
@click.pass_obj
def host_grp(obj, domain):
    """Manage hosts."""
    obj.domain = domain


@host_grp.command(name="show")
@click.option("--type", "-t", "type_", type=str, help="Thing type to filter by")
@click.pass_obj
def host_show(obj, type_):
    """Show a host or list all hosts."""
    sess = obj.session
    if obj.domain is not None:
        h = _get_one(obj, Host, "host", domain=obj.domain)
        yprint(h.dump())
        return

    sel = select(Host)
    if type_ is not None:
        from moat.db.thing.model import Thing, ThingTyp  # noqa: PLC0415

        ttyp = sess.one(ThingTyp, name=type_)
        thing_ids = select(Thing.id).where(Thing.thingtyp == ttyp)
        sel = sel.where(Host.thing_id.in_(thing_ids))
    with sess.execute(sel.order_by(Host.domain)) as rs:
        for (h,) in rs:
            print(h.domain, h.thing.name if h.thing else "?")


def host_opts(c):
    c = option_ng("--name", "-N", type=str, help="Short name (on the Thing)")(c)
    c = option_ng("--domain", "-d", type=str, help="FQDN")(c)
    c = option_ng("--loc", "-l", type=str, help="Physical location")(c)
    c = option_ng("--thingtyp", "-t", type=str, help="Thing type (default: host)")(c)
    c = option_ng("--descr", "-D", type=str, help="Description (on the Thing)")(c)
    return c


@host_grp.command(name="add")
@host_opts
@click.pass_obj
def host_add(obj, **kw):
    """Add a host."""
    domain = obj.domain
    if domain is None:
        raise click.UsageError("The host needs a domain (--domain)!")
    _absent(obj, Host, "host", domain=domain)
    h = Host(domain=domain)
    obj.session.add(h)
    h.apply(**kw)


@host_grp.command(name="set")
@host_opts
@click.pass_obj
def host_set(obj, **kw):
    """Modify a host."""
    h = _get_one(obj, Host, "host", domain=obj.domain)
    h.apply(**kw)


@host_grp.command(name="delete")
@click.pass_obj
def host_delete(obj):
    """Delete a host (and its Thing)."""
    h = _get_one(obj, Host, "host", domain=obj.domain)
    obj.session.delete(h)


# ---------------------------------------------------------------------------
# Host → Interface
# ---------------------------------------------------------------------------


@host_grp.group(name="iface")
@click.argument("iname", type=str)
@click.pass_obj
def iface_grp(obj, iname):
    """Manage interfaces of a host.

    Use '.' for the empty-named interface (former direct attachment).
    """
    obj.iname = _norm_iface(iname)


@iface_grp.command(name="show")
@click.pass_obj
def iface_show(obj):
    """Show an interface or list all interfaces of the host."""
    h = _get_one(obj, Host, "host", domain=obj.domain)

    if obj.iname == "" and not obj.__dict__.get("_iface_explicit"):
        # List all interfaces
        seen = False
        for i in sorted(h.interfaces, key=lambda x: x.name):
            seen = True
            print(i.name or ".", i.vlan.name if i.vlan else "-", str(i.mac) if i.mac else "-")
        if not seen:
            print("No interfaces. Use '--help'?", file=sys.stderr)
    else:
        i = _get_one(obj, Interface, "interface", host=h, name=obj.iname)
        yprint(i.dump())


def iface_opts(c):
    c = option_ng("--name", "-N", type=str, help="Rename this interface")(c)
    c = option_ng("--vlan", "-V", type=str, help="VLAN this interface is on")(c)
    c = option_ng("--mac", "-m", type=str, help="MAC address")(c)
    c = option_ng("--seqnum", "-s", type=int, help="Sequence number in the VLAN")(c)
    c = option_ng("--desc", "-d", type=str, help="Description")(c)
    c = option_ng("--alloc", "-a", is_flag=True, help="Allocate a free seqnum")(c)
    return c


@iface_grp.command(name="add")
@iface_opts
@click.pass_obj
def iface_add(obj, **kw):
    """Add an interface to a host."""
    h = _get_one(obj, Host, "host", domain=obj.domain)
    _absent(obj, Interface, "interface", host=h, name=obj.iname)
    i = Interface(host=h, name=obj.iname)
    obj.session.add(i)

    alloc = kw.pop("alloc", NotGiven)
    if alloc is not NotGiven and alloc:
        kw["seqnum"] = _alloc_seqnum(obj, h, kw.get("vlan", NotGiven))

    i.apply(host=obj.domain, **kw)


@iface_grp.command(name="set")
@iface_opts
@click.pass_obj
def iface_set(obj, **kw):
    """Modify an interface."""
    h = _get_one(obj, Host, "host", domain=obj.domain)
    i = _get_one(obj, Interface, "interface", host=h, name=obj.iname)

    alloc = kw.pop("alloc", NotGiven)
    if alloc is not NotGiven and alloc:
        kw["seqnum"] = _alloc_seqnum(obj, h, kw.get("vlan", NotGiven))

    i.apply(**kw)


@iface_grp.command(name="delete")
@click.pass_obj
def iface_delete(obj):
    """Delete an interface."""
    h = _get_one(obj, Host, "host", domain=obj.domain)
    i = _get_one(obj, Interface, "interface", host=h, name=obj.iname)
    obj.session.delete(i)


@iface_grp.command(name="link")
@click.argument("dest", type=str)
@click.pass_obj
def iface_link(obj, dest):
    """Create a cable between this interface and another.

    DEST is specified as ``DOMAIN:IFACE`` (use ``.`` for the direct
    interface).
    """
    h = _get_one(obj, Host, "host", domain=obj.domain)
    src_iface = _get_one(obj, Interface, "interface", host=h, name=obj.iname)
    dst_iface = _resolve_iface_spec(obj, dest)

    # Check neither endpoint is already cabled
    if src_iface.cable_a or src_iface.cable_b:
        raise click.UsageError(f"Interface {obj.domain}:{obj.iname or '.'} is already cabled.")
    if dst_iface.cable_a or dst_iface.cable_b:
        raise click.UsageError(f"Interface {dest} is already cabled.")

    cable = Cable(iface_a=src_iface, iface_b=dst_iface)
    obj.session.add(cable)


def _alloc_seqnum(obj, _host, vlan_name) -> int:
    """Find the first free seqnum on a VLAN, skipping the DHCP range."""
    if vlan_name is NotGiven or vlan_name is None:
        raise click.UsageError("Need a VLAN to allocate a seqnum.")
    vlan = _get_one(obj, Vlan, "VLAN", name=vlan_name)

    # Collect used seqnums on this VLAN
    used: set[int] = set()
    with obj.session.execute(
        select(Interface.seqnum).where(Interface.vlan == vlan, Interface.seqnum.is_not(None))
    ) as rs:
        for (s,) in rs:
            used.add(s)

    # Determine DHCP range to skip
    dhcp_first: int | None = None
    dhcp_last: int | None = None
    for net in vlan.networks:
        if net.dhcp_first is not None and net.dhcp_count is not None:
            df = net.dhcp_first
            dl = df + net.dhcp_count - 1
            if dhcp_first is None or df < dhcp_first:
                dhcp_first = df
            if dhcp_last is None or dl > dhcp_last:
                dhcp_last = dl

    seqnum = 1
    while True:
        if seqnum in used:
            seqnum += 1
            continue
        if dhcp_first is not None and dhcp_last is not None and dhcp_first <= seqnum <= dhcp_last:
            seqnum = dhcp_last + 1
            continue
        return seqnum


def _resolve_iface_spec(obj, spec: str) -> Interface:
    """Resolve a ``DOMAIN:IFACE`` spec to an Interface row."""
    try:
        domain, iname = spec.split(":", 1)
    except ValueError:
        raise click.UsageError(f"Bad interface spec {spec!r}; use 'domain:iface'.") from None
    iname = _norm_iface(iname)
    h = _get_one(obj, Host, "host", domain=domain)
    return _get_one(obj, Interface, "interface", host=h, name=iname)


# ---------------------------------------------------------------------------
# Host → Interface → Address
# ---------------------------------------------------------------------------


@iface_grp.group(name="addr")
@click.pass_obj
def addr_grp(obj):
    """Manage addresses on an interface."""
    pass


@addr_grp.command(name="show")
@click.pass_obj
def addr_show(obj):
    """Show addresses on an interface."""
    h = _get_one(obj, Host, "host", domain=obj.domain)
    i = _get_one(obj, Interface, "interface", host=h, name=obj.iname)
    for a in sorted(i.addresses, key=lambda x: x.addr):
        print(str(a.ip.ip))
    if i.link_local is not None:
        print(f"link-local: {i.link_local} (computed, not stored)")


@addr_grp.command(name="add")
@click.option("--addr", "-a", type=str, required=True, help="IP address (e.g. 10.0.0.5/24)")
@click.pass_obj
def addr_add(obj, addr):
    """Add a manual address to an interface."""
    h = _get_one(obj, Host, "host", domain=obj.domain)
    i = _get_one(obj, Interface, "interface", host=h, name=obj.iname)
    a = Address(interface=i)
    obj.session.add(a)
    a.apply(ip=addr)


@addr_grp.command(name="delete")
@click.option("--addr", "-a", type=str, required=True, help="IP address to remove")
@click.pass_obj
def addr_delete(obj, addr):
    """Remove a manual address from an interface."""
    from .ip import IpValue  # noqa: PLC0415

    h = _get_one(obj, Host, "host", domain=obj.domain)
    i = _get_one(obj, Interface, "interface", host=h, name=obj.iname)
    target = IpValue.from_ip(addr)
    for a in i.addresses:
        if a.addr == target.addr:
            obj.session.delete(a)
            return
    raise click.UsageError(f"Address {addr} not found on this interface.")


# ---------------------------------------------------------------------------
# Wire (thin specialization of host)
# ---------------------------------------------------------------------------


@cli.group(name="wire")
@click.option("--domain", "-d", type=str, help="FQDN of the wire")
@click.pass_obj
def wire_grp(obj, domain):
    """Manage wires (hosts with thing type 'wire' and two interfaces a/b)."""
    obj.domain = domain


@wire_grp.command(name="show")
@click.pass_obj
def wire_show(obj):
    """Show a wire or list all wires."""
    sess = obj.session
    from moat.db.thing.model import ThingTyp  # noqa: PLC0415

    if obj.domain is not None:
        h = _get_one(obj, Host, "wire", domain=obj.domain)
        yprint(h.dump())
        return

    ttyp = sess.one(ThingTyp, name="wire")
    from moat.db.thing.model import Thing  # noqa: PLC0415

    thing_ids = select(Thing.id).where(Thing.thingtyp == ttyp)
    with sess.execute(
        select(Host).where(Host.thing_id.in_(thing_ids)).order_by(Host.domain)
    ) as rs:
        seen = False
        for (h,) in rs:
            seen = True
            print(h.domain)
        if not seen:
            print("No wires defined yet. Use '--help'?", file=sys.stderr)


def wire_opts(c):
    c = option_ng("--name", "-N", type=str, help="Short name (on the Thing)")(c)
    c = option_ng("--domain", "-d", type=str, help="FQDN")(c)
    c = option_ng("--loc", "-l", type=str, help="Physical location")(c)
    c = option_ng("--descr", "-D", type=str, help="Description (on the Thing)")(c)
    return c


@wire_grp.command(name="add")
@wire_opts
@click.pass_obj
def wire_add(obj, **kw):
    """Add a wire (creates a host with thing type 'wire' and interfaces a/b)."""
    domain = obj.domain
    if domain is None:
        raise click.UsageError("The wire needs a domain (--domain)!")
    _absent(obj, Host, "wire", domain=domain)
    kw["thingtyp"] = "wire"
    h = Host(domain=domain)
    obj.session.add(h)
    h.apply(**kw)
    # Create the two interfaces
    obj.session.add(Interface(host=h, name="a"))
    obj.session.add(Interface(host=h, name="b"))


@wire_grp.command(name="set")
@wire_opts
@click.pass_obj
def wire_set(obj, **kw):
    """Modify a wire."""
    h = _get_one(obj, Host, "wire", domain=obj.domain)
    h.apply(**kw)


@wire_grp.command(name="delete")
@click.pass_obj
def wire_delete(obj):
    """Delete a wire (and its Thing)."""
    h = _get_one(obj, Host, "wire", domain=obj.domain)
    obj.session.delete(h)


@wire_grp.command(name="link")
@click.option(
    "--end",
    "-e",
    type=click.Choice(["a", "b"]),
    default="b",
    help="Which end to link (default: b)",
)
@click.argument("dest", type=str)
@click.pass_obj
def wire_link(obj, end, dest):
    """Connect a wire endpoint to another interface.

    Links the 'b' end (farther from the main router) by default.
    """
    h = _get_one(obj, Host, "wire", domain=obj.domain)
    src_iface = _get_one(obj, Interface, "interface", host=h, name=end)
    dst_iface = _resolve_iface_spec(obj, dest)

    if src_iface.cable_a or src_iface.cable_b:
        raise click.UsageError(f"Wire {obj.domain}:{end} is already cabled.")
    if dst_iface.cable_a or dst_iface.cable_b:
        raise click.UsageError(f"Interface {dest} is already cabled.")

    cable = Cable(iface_a=src_iface, iface_b=dst_iface)
    obj.session.add(cable)


# ---------------------------------------------------------------------------
# Cable
# ---------------------------------------------------------------------------


@cli.group(name="cable")
@click.pass_obj
def cable_grp(obj):
    """Manage cables."""
    pass


@cable_grp.command(name="show")
@click.pass_obj
def cable_show(obj):
    """List all cables."""
    sess = obj.session
    with sess.execute(select(Cable)) as rs:
        seen = False
        for (c,) in rs:
            seen = True
            a = c.iface_a
            b = c.iface_b
            print(f"{c.id}\t{a.host.domain}:{a.name or '.'} ↔ {b.host.domain}:{b.name or '.'}")
        if not seen:
            print("No cables defined yet.", file=sys.stderr)


# ---------------------------------------------------------------------------
# HostGroup
# ---------------------------------------------------------------------------


@cli.group(name="group")
@click.option("--name", "-n", type=str, help="Group name")
@click.pass_obj
def group_grp(obj, name):
    """Manage host groups."""
    obj.name = name


@group_grp.command(name="show")
@click.pass_obj
def group_show(obj):
    """Show a group or list all groups."""
    sess = obj.session
    if obj.name is None:
        seen = False
        with sess.execute(select(HostGroup).order_by(HostGroup.name)) as rs:
            for (g,) in rs:
                seen = True
                print(g.name)
        if not seen:
            print("No groups defined yet. Use '--help'?", file=sys.stderr)
    else:
        g = _get_one(obj, HostGroup, "group", name=obj.name)
        yprint(g.dump())


def group_opts(c):
    c = option_ng("--name", "-n", type=str, help="Rename this group")(c)
    c = option_ng("--desc", "-d", type=str, help="Description")(c)
    return c


@group_grp.command(name="add")
@group_opts
@click.pass_obj
def group_add(obj, **kw):
    """Add a group."""
    name = _require(obj, "group")
    _absent(obj, HostGroup, "group", name=name)
    g = HostGroup(name=name)
    obj.session.add(g)
    g.apply(**kw)


@group_grp.command(name="set")
@group_opts
@click.pass_obj
def group_set(obj, **kw):
    """Modify a group."""
    g = _get_one(obj, HostGroup, "group", name=obj.name)
    g.apply(**kw)


@group_grp.command(name="delete")
@click.pass_obj
def group_delete(obj):
    """Delete a group."""
    g = _get_one(obj, HostGroup, "group", name=obj.name)
    obj.session.delete(g)


# ---------------------------------------------------------------------------
# Host → HostGroup membership
# ---------------------------------------------------------------------------


@host_grp.group(name="group")
@click.option("--name", "-g", type=str, help="Group name")
@click.pass_obj
def host_group_grp(obj, name):
    """Manage group memberships of a host."""
    obj.group_name = name


@host_group_grp.command(name="show")
@click.pass_obj
def host_group_show(obj):
    """Show groups of a host."""
    h = _get_one(obj, Host, "host", domain=obj.domain)
    for g in sorted(h.groups, key=lambda x: x.name):
        print(g.name)


@host_group_grp.command(name="add")
@click.pass_obj
def host_group_add(obj):
    """Add a host to a group."""
    h = _get_one(obj, Host, "host", domain=obj.domain)
    g = _get_one(obj, HostGroup, "group", name=obj.group_name)
    h.groups.add(g)


@host_group_grp.command(name="delete")
@click.pass_obj
def host_group_delete(obj):
    """Remove a host from a group."""
    h = _get_one(obj, Host, "host", domain=obj.domain)
    g = _get_one(obj, HostGroup, "group", name=obj.group_name)
    h.groups.discard(g)
