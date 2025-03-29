# command line interface
from __future__ import annotations

import logging
import os
import sys
from collections import deque
from operator import attrgetter
from pprint import pprint

import asyncclick as click
from moat.kv.data import data_get
from moat.kv.obj.command import std_command
from moat.util import P, attrdict
from netaddr import EUI, AddrFormatError, IPAddress, IPNetwork

from moat.kv.inv.model import Host, InventoryRoot, Wire

logger = logging.getLogger(__name__)


@click.group(short_help="Manage computer inventory.")
@click.pass_obj
async def cli(obj):
    """
    Inventorize your computers, networks, and their connections.
    """
    obj.data = await InventoryRoot.as_handler(obj.client)


@cli.command("dump")
@click.argument("path", nargs=1)
@click.pass_obj
async def dump_(obj, path):
    """Emit the current state as a YAML file."""
    path = P(path)
    await data_get(obj, obj.cfg.inv.prefix + path)


std_command(
    cli,
    "vlan",
    "id",
    int,
    aux=(
        click.option("-d", "--desc", type=str, default=None, help="Description"),
        click.option("-w", "--wlan", type=str, default=None, help="WLAN SSID"),
        click.option("-p", "--passwd", type=str, default=None, help="WLAN pasword"),
    ),
    short_help="Manage VLANs",
)


def rev_name(ctx, param, value, *, delim=".", rev=True):  # pylint: disable=unused-argument
    value = value.split(delim)
    if len(value) < 3:
        raise click.BadParameter("need more than two labels")
    if any(not v for v in value):
        raise click.BadParameter("no empty labels")
    if rev:
        value.reverse()
    return value


def rev_wire(ctx, param, value):
    return rev_name(ctx, param, value, delim="-", rev=False)


def host_post(obj, h, values):
    net = values.get("net", None)
    if net not in (None, "-"):
        n = obj.data.net.by_name(net)
        if n is None:
            try:
                na = IPAddress(net)
            except AddrFormatError:
                raise click.exceptions.UsageError("malformed network: " + repr(net)) from None
            n = obj.data.net.enclosing(na)
            if n is None:
                raise RuntimeError("Network unknown", net)
            if not values.get("num"):
                num = na.value - n.net.value
                if values.get("alloc") and num:
                    raise RuntimeError("Need net address when allocating")
                if num:
                    values["num"] = num
            values["net"] = n.name

    if values.pop("alloc", None):
        if values.get("num"):
            raise click.BadParameter("'num' and 'alloc' are mutually exclusive'", "alloc")
        net = values.get("net", None) or (h.net if h else None)
        if net is None:
            raise click.BadParameter("Need a network to allocate a number in")
        values["num"] = obj.data.net.by_name(net).alloc()


def get_net(ctx, attr, val):  # pylint: disable=unused-argument
    if val in (None, "-"):
        return val
    return val


def get_net_name(ctx, attr, val):  # pylint: disable=unused-argument
    if val is None:
        return None
    n = ctx.obj.data.net.by_name(val)
    if n is None:
        return KeyError(val)
    return n


def get_net_tuple(ctx, attr, val):  # pylint: disable=unused-argument
    val = IPNetwork(val)
    return val.prefixlen, val.value


def get_mac(ctx, attr, val):  # pylint: disable=unused-argument
    if val in (None, "-"):
        return val
    return EUI(val)


def net_apply(obj, n, kw):  # pylint:disable=unused-argument
    seen = 0
    val = kw.pop("virt", None)
    if val is not None:
        n.virt = val
    if kw.pop("mac"):
        n.mac = True
        seen += 1
    if kw.pop("no_mac"):
        n.mac = False
        seen += 1
    if kw.pop("both_mac"):
        n.mac = None
        seen += 1
    if seen > 1:
        raise click.UsageError("Only one of -m/-M/-B please.")
    if n.mac is True:
        if kw["shift"] > 0:
            raise click.UsageError("You need to actually use the hostnum in order to shift it")
        n.shift = -1
    elif n.shift < 0:
        n.shift = 0


std_command(
    cli,
    "net",
    "net",
    str,
    id_cb=get_net_tuple,
    aux=(
        click.option("-d", "--desc", type=str, default=None, help="Description"),
        click.option("-v", "--vlan", type=str, default=None, help="VLAN to use"),
        click.option("-a", "--dhcp", type=int, nargs=2, help="DHCP first+length"),
        click.option("-m", "--mac", is_flag=True, help="use MAC as host part"),
        click.option("-V/-R", "--virt/--real", is_flag=True, help="Network without cables="),
        click.option("-M", "--no-mac", is_flag=True, help="use hostnum"),
        click.option("-B", "--both-mac", is_flag=True, help="use both MAC and hostnum (default)"),
        click.option(
            "-S",
            "--master",
            type=str,
            default=None,
            help="Network to attach this to",
            callback=get_net_name,
        ),
        click.option("-s", "--shift", type=int, default=0, help="Shift for host number"),
    ),
    apply=net_apply,
    short_help="Manage networks",
    list_recursive=True,
)


cmd_host = std_command(
    cli,
    "host",
    "domain",
    str,
    id_cb=rev_name,
    aux=(
        click.option("-d", "--desc", type=str, default=None, help="Description"),
        click.option("-l", "--loc", type=str, default=None, help="Location"),
        click.option("-n", "--net", type=str, default=None, help="Network", callback=get_net),
        click.option("-N", "--name", type=str, default=None, help="Name (not when adding)"),
        click.option("-m", "--mac", type=str, default=None, help="MAC", callback=get_mac),
        click.option("-i", "--num", type=int, default=None, help="Position in network"),
        click.option("-a", "--alloc", is_flag=True, default=None, help="Auto-allocate network ID"),
    ),
    apply=host_post,
    short_help="Manage hosts",
    list_recursive=True,
)


@cmd_host.group(name="port", short_help="Manage ports", invoke_without_command=True)
@click.argument("name", type=str, nargs=1)
@click.pass_context
async def host_port(ctx, name):
    """\
        Manager for ports.

        \b
        Use '… port -' to list all entries.
        Use '… port NAME' to show details of a single entry.
        """

    obj = ctx.obj
    h = obj.host
    if name == "-":
        if ctx.invoked_subcommand is not None:
            raise click.BadParameter("The name '-' triggers a list and precludes subcommands.")
        for k, v in h.ports.items():
            p = h._ports[k]
            print(k, v, file=obj.stdout)
    elif ctx.invoked_subcommand is None:
        p = h.port[name]
        for k in p.ATTRS + p.AUX_ATTRS + p.ATTRS2:
            v = getattr(p, k)
            if v is not None:
                print(k, v, file=obj.stdout)
    else:
        obj.thing_port = name
        # click invokes the subcommand for us.


@cmd_host.command(name="template", short_help="Create config file using a template")
@click.option("-d", "--dump", is_flag=True, help="Dump the template's replacement data")
@click.argument("template", type=click.Path("r"), nargs=-1)
@click.pass_obj
async def host_template(obj, dump, template):
    """\
        Load a template, for generating a host configuration file.

        The template is interpreted with jinja2.

        \b
        Variables:
            host   this host
            ports  a list of the host's ports
            vlans  the VLANs attached to this host
        """
    import jinja2

    if len(template) != 1 - dump:
        if dump:
            raise click.BadParameter("You can't add a template file name when dumping.")
        else:
            raise click.BadParameter("You need to tell me which template to use.")

    if not dump:
        e = jinja2.Environment(
            loader=jinja2.FileSystemLoader(os.path.dirname(template[0])),
            autoescape=False,
        )
        t = e.get_template(os.path.basename(template[0]))
    h = obj.host

    nport = {}
    ports = {}
    one = None
    none = None

    for vl in obj.data.vlan.all_children:
        if vl.vlan == 1:
            one = vl
        elif vl.name == "init":
            none = vl
        nport[vl] = 0

    for p in h._ports.values():
        ports[p.name] = pn = attrdict(
            port=p,
            untagged=None,
            tagged=set(),
            blocked=set(nport.keys()),
            single=set(),
        )
        if pn.port.network is None:
            continue

        a3 = (pn.port.network.net.value >> 8) & 0xFF
        a4 = pn.port.network.net.value & 0xFF
        nv = pn.port.netaddr.value & ~pn.port.netaddr.netmask.value

        pn.net6 = IPNetwork(f"2001:780:107:{a3:02x}{a4:02x}::1/64")
        pn.ip6 = IPNetwork(
            f"2001:780:107:{a3:02x}{a4:02x}::{nv:x}/64",
        )

    for d in ports.values():
        va = d.port.vlan
        vb = d.port.other_end.vlan if d.port.other_end else None
        if va is None:
            va = vb
        elif vb is not None and va != vb:
            print(f"Warning! inconsistent VLANs on port {d.port}", file=sys.stderr)

        vs = await d.port.connected_vlans()
        for vl in vs:
            nport[vl] += 1
            d.tagged.add(vl)
            d.blocked.remove(vl)
        if va:
            d.untagged = va
            d.blocked.discard(va)
            d.tagged.discard(va)
        elif not d.tagged:  # port empty
            nport[none] += 1
            d.untagged = none
            d.blocked.discard(none)

    vl_one = set(k for k, v in nport.items() if v <= 1)

    for d in ports.values():
        if len(d.tagged) == 1 and not d.untagged:
            d.untagged = d.tagged.pop()
        else:
            if one in d.tagged:
                d.untagged = one
                d.tagged.discard(one)
            d.single = vl_one & d.tagged
            d.tagged -= vl_one
            d.blocked |= vl_one
    data = dict(host=h, vlans=nport, ports=list(ports.values()))
    if dump:
        pprint(data, stream=obj.stdout)
    else:
        print(t.render(**data), file=obj.stdout)


@cmd_host.command(name="find", short_help="Show the path to another host")
@click.argument("dest", type=str, nargs=1)
@click.pass_obj
async def host_find(obj, dest):
    """\
        Find the path to another host.

        A destination of '-' lists all unreachable hosts.
        """
    seen = set()
    h = obj.host
    todo = deque()
    todo.append((h, ()))

    def work():
        # Enumerate all connected hosts.
        # Wires are duck-typed as hosts with two ports.
        while todo:
            w, wp = todo.popleft()
            wx = w
            if hasattr(w, "host"):
                w = w.host
            if w in seen:
                continue
            seen.add(w)
            yield wx, wp

            if hasattr(w, "port"):
                for p in w.port.values():
                    c = p.link_to
                    if c is not None:
                        todo.append((c, wp + (p, c)))

    if dest == "-":
        for hp, _ in work():
            pass
        for hp in obj.data.host.all_children:
            if hp not in seen:
                print(hp, file=obj.stdout)
    else:
        for hp, p in work():
            if isinstance(hp, Host):
                hx = hp
            else:
                hx = hp.host
            if hx.name != dest:
                continue

            pr = []
            px = None
            # For routes through hosts, we print both host+port names.
            # For wires, only the single wire name is interesting.
            for pp in p:
                if getattr(pp, "host", None) is getattr(px, "host", False) and isinstance(
                    pp.host,
                    Wire,
                ):
                    pr.append(pp.host)
                    px = None
                else:
                    if px is not None:
                        pr.append(px)
                    px = pp

            if px is not None:
                pr.append(px)
            print(*(p.name if isinstance(p, Wire) else p for p in pr), file=obj.stdout)
            break


std_command(cli, "group", short_help="Manage host config groups")

cmd_wire = std_command(
    cli,
    "wire",
    name_cb=rev_wire,
    short_help="Manage wire links",
    aux=(
        click.option("-d", "--desc", type=str, default=None, help="Description"),
        click.option("-l", "--loc", type=str, default=None, help="Location"),
    ),
)


@cmd_wire.command(name="link", short_help="Link two wires")
@click.argument("dest", type=str, nargs=-1)
@click.option("-A", "--a-ends", is_flag=True, help="Link the A ends")
@click.option("-f", "--force", is_flag=True, help="Replace existing cables")
@click.pass_obj
async def wire_link(obj, dest, a_ends, force):
    """\
        Link the B ends of two wires.

        The A end of a wire is the one closer to the main router.

        If you need to connect the wire to a port, use this command there.
        """

    w = obj.wire
    if len(dest) > 1:
        raise click.BadParameter("Too many destination parameters")
    if not dest:
        print(obj.data.cable.cable_for(w), file=obj.stdout)
        return
    if dest[0] == "-":
        await obj.data.cable.unlink(w)
    else:
        d = obj.data.wire.by_name(dest[0])
        if d is None:
            raise KeyError(dest)
        if a_ends:
            w = w.port["a"]
            d = d.port["a"]
        else:
            w = w.port["b"]
            d = d.port["b"]
        await obj.data.cable.link(w, d, force=force)


@cli.command(short_help="Manage cables")
@click.pass_context
async def cable(ctx):
    """
    List cables
    """
    obj = ctx.obj
    if ctx.invoked_subcommand is not None:
        return
    for c in obj.data.cable.all_children:
        print(c, file=obj.stdout)


def _hp_args(p):
    p = click.option("-d", "--desc", type=str, default=None, help="Description")(p)
    p = click.option("-v", "--vlan", type=str, default=None, help="VLAN")(p)

    p = click.option("-m", "--mac", type=str, default=None, help="MAC", callback=get_mac)(p)
    p = click.option("-n", "--net", type=str, default=None, help="Network", callback=get_net)(p)
    p = click.option("-i", "--num", type=int, default=None, help="Position in network")(p)
    p = click.option("-a", "--alloc", is_flag=True, help="Auto-allocate network ID")(p)
    return p


@host_port.command(name="add", short_help="add a port")
@_hp_args
@click.pass_obj
async def hp_add(obj, **kw):
    """\
        Add a port to a host.
        """
    h = obj.host
    port = obj.thing_port
    if port in h.port:
        raise click.BadParameter("This port already exists")
    p = h.add_port(port)

    await _hp_mod(obj, p, **kw)
    await h.save()


@host_port.command(name="set", short_help="configure a port")
@_hp_args
@click.option("-N", "--name", type=str, default=None, help="Rename this interface")
@click.pass_obj
async def hp_set(obj, name, **kw):
    """\
        Set port parameters.
        """
    h = obj.host
    p = h.port[obj.thing_port]
    if name:
        await p.rename(name)
    await _hp_mod(obj, p, **kw)
    await h.save()


async def _hp_mod(obj, p, **kw):
    net = kw.get("net")

    if net not in (None, "-"):
        n = p.host.root.net.by_name(net)
        if n is None:
            try:
                na = IPAddress(net)
            except AddrFormatError:
                raise click.exceptions.UsageError("malformed network: " + repr(net)) from None
            n = p.host.root.net.enclosing(na)
            if n is None:
                raise RuntimeError("Network unknown", net)
            if not kw.get("num"):
                num = na.value - n.net.value
                if kw.get("alloc") and num:
                    raise RuntimeError("Need net address when allocating")
                if num:
                    kw["num"] = num
            kw["net"] = n.name

    if kw.pop("alloc", None):
        if kw.get("num"):
            raise click.BadParameter("'num' and 'alloc' are mutually exclusive'", "alloc")
        net = kw.get("net") or (p.net if p else None)
        if net is None:
            raise click.BadParameter("Need a network to allocate a number in")
        kw["num"] = obj.host.root.net.by_name(net).alloc()

    for k, v in kw.items():
        if v is None:
            continue
        if v == "-":
            setattr(p, k, None)
            continue
        if k == "vlan" and obj.data.vlan.by_name(v) is None:
            raise click.BadParameter("VLAN does not exist")
        setattr(p, k, v)


@host_port.command(name="delete", short_help="delete a port")
@click.pass_obj
async def hp_delete(obj):
    """\
        Delete a port.
        """
    h = obj.host
    p = h.port[obj.thing_port]
    await h.delete_port(p)


@host_port.command(name="link", short_help="Link a port to another host/port")
@click.argument("dest", type=str, nargs=-1)
@click.option("-A", "--a-end", is_flag=True, help="Dest is a wire, link to A end")
@click.option("-B", "--b-end", is_flag=True, help="Dest is a wire, link to B end")
@click.option("-f", "--force", is_flag=True, help="Replace existing cables")
@click.pass_obj
async def hp_link(obj, dest, a_end, b_end, force):
    """\
        Link a port to another host or port.
        """
    h = obj.host
    port = obj.thing_port
    if len(dest) > 2 or ((dest and dest[0] == "-" or a_end or b_end) and len(dest) > 1):
        raise click.BadParameter("Too many destination params")
    try:
        p = h.port[port]
    except KeyError:
        raise click.BadParameter(f"Unknown port {port!r}") from None
    if not dest:
        print(obj.data.cable.cable_for(p), file=obj.stdout)
        return
    if dest[0] == "-":
        await obj.data.cable.unlink(p)
    else:
        d = attrgetter("wire" if a_end or b_end else "host")(obj.data).by_name(dest[0])
        if d is None:
            raise KeyError(dest)
        if a_end:
            d = d.port["a"]
        elif b_end:
            d = d.port["b"]
        elif len(dest) > 1:
            d = d.port[dest[1]]
        await obj.data.cable.link(p, d, force=force)
