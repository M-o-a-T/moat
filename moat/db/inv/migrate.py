"""
One-time import of the MoaT-KV inventory (:mod:`moat.kv.inv`) into
:mod:`moat.db.inv`.

The importer works on the raw KV entries below the inventory prefix, as
``(path, value)`` pairs, so it can read them from a live MoaT-KV server or
from the output of ``moat kv data PREFIX get -r``. See
``docs/moat-db-inv/MIGRATION.md`` ("Data migration") for the mapping.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field

from netaddr import EUI, IPNetwork
from sqlalchemy import select

from moat.db.thing.model import Thing, ThingTyp

from .model import Cable, Host, HostGroup, Interface, Network, Vlan

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from moat.lib.path import Path

    from collections.abc import Iterable

__all__ = ["Report", "import_inv", "kv_items"]

_PORT_KEYS = {"desc", "mac", "net", "num", "vlan"}


@dataclass
class Report:
    """What the importer did, and what needs an operator's attention."""

    counts: dict[str, int] = field(default_factory=dict)
    """Rows created, by kind."""
    skipped: list[str] = field(default_factory=list)
    """Entries that could not be imported."""
    changed: list[str] = field(default_factory=list)
    """Entries imported with a change that should be reviewed."""
    expanded: list[str] = field(default_factory=list)
    """Interfaces that now get addresses on more than one network (MIGRATION.md)."""
    attrs: list[str] = field(default_factory=list)
    """Port attributes that were dropped (MIGRATION.md Q7)."""

    def dump(self) -> dict[str, Any]:
        """The report as plain data."""
        return {k: v for k, v in vars(self).items() if v}


@dataclass
class _Net:
    name: str
    net: IPNetwork
    vlan: str | None
    shift: int
    data: dict[str, Any]


def kv_items(entries: Iterable[Any]) -> list[tuple[Path, Any]]:
    """
    Convert ``moat kv data … get -r`` output to ``(path, value)`` pairs.

    Args:
        entries: The loaded YAML list; each entry is a single ``{path: value}``
            mapping.
    """
    res: list[tuple[Path, Any]] = []
    for e in entries:
        if not isinstance(e, Mapping) or len(e) != 1:
            raise ValueError(f"Not a 'get -r' entry: {e!r}")
        ((path, value),) = e.items()
        res.append((path, value))
    return res


def _mac(m: Any) -> EUI | None:
    if m is None:
        return None
    if isinstance(m, bytes | bytearray):
        return EUI(int.from_bytes(m, "big"), version=len(m) * 8)
    return EUI(m)


def _thingtyp(sess, name: str) -> ThingTyp:
    try:
        return sess.one(ThingTyp, name=name)
    except KeyError:
        t = ThingTyp(name=name)
        sess.add(t)
        return t


class _Importer:
    def __init__(self, sess, report: Report) -> None:
        self.sess = sess
        self.r = report
        self.vlans: dict[str, Vlan] = {}  # by name and by str(tag)
        self.nets: dict[str, _Net] = {}
        self.networks: dict[str, Network] = {}
        self.groups: dict[str, HostGroup] = {}
        self.hosts: dict[tuple, Host] = {}  # by KV subpath
        self.ifaces: dict[tuple, dict[str, Interface]] = {}
        self.seq: dict[tuple[int, int], str] = {}

    def count(self, kind: str) -> None:
        self.r.counts[kind] = self.r.counts.get(kind, 0) + 1

    # VLANs and networks

    def vlan(self, tag: int, v: dict[str, Any]) -> None:
        name = v.get("name") or str(tag)
        vl = Vlan(tag=tag, name=name)
        for k in ("desc", "wlan", "passwd"):
            if v.get(k) is not None:
                setattr(vl, k, v[k])
        self.sess.add(vl)
        self.vlans[name] = vl
        self.vlans.setdefault(str(tag), vl)
        self.count("vlan")

    def find_vlan(self, v: Any) -> Vlan | None:
        if v is None or isinstance(v, bool):
            return None
        return self.vlans.get(str(v))

    def net(self, prefix: int, num: int | bytes, v: dict[str, Any]) -> None:
        if isinstance(num, bytes):
            num = int.from_bytes(num, "big")
        net = IPNetwork((num, prefix))
        name = v.get("name") or str(net)
        self.nets[name] = _Net(name, net, v.get("vlan"), v.get("shift") or 0, v)

    def networks_(self) -> None:
        for n in self.nets.values():
            vl = self.find_vlan(n.vlan)
            master = self.nets.get(n.data.get("master"))
            if vl is None and master is not None:
                # a slave net shares its master's VLAN (MIGRATION.md D3)
                vl = self.find_vlan(master.vlan)
                n.vlan = vl.name if vl is not None else None
            if vl is None:
                self.r.skipped.append(f"net {n.name} ({n.net}): no VLAN")
                continue
            v = n.data
            nw = Network(
                name=n.name,
                shift=n.shift,
                desc=v.get("desc"),
                virt=bool(v.get("virt", False)),
            )
            nw.vlan = vl
            nw.apply(subnet=str(n.net))
            a, b = v.get("dhcp") or (None, 0)
            if b:
                nw.dhcp_first, nw.dhcp_count = a, b
            for k in ("wlan", "passwd"):
                if v.get(k) is not None and getattr(vl, k) is None:
                    setattr(vl, k, v[k])
                    self.r.changed.append(f"net {n.name}: {k} moved to VLAN {vl.name}")
            self.sess.add(nw)
            self.networks[n.name] = nw
            self.count("network")

    def resolve_net(self, net: Any, num: Any) -> tuple[_Net | None, int | None]:
        """A host/port ``net`` value (a name or ``addr/prefix``) → network and seqnum."""
        if net is None:
            return None, num
        n = self.nets.get(net)
        if n is not None:
            return n, num
        with contextlib.suppress(Exception):
            ip = IPNetwork(net)
            for n in self.nets.values():
                if n.net.prefixlen == ip.prefixlen and ip.ip in n.net:
                    if num is None:
                        num = (int(ip.ip) - int(n.net.network)) >> n.shift
                    return n, num
        return None, num

    def family(self, n: _Net) -> set[str]:
        """A net plus its master and slaves: KV already gave hosts addresses on all of them."""
        res = {n.name}
        if (master := n.data.get("master")) is not None:
            res.add(master)
        res.update(m.name for m in self.nets.values() if m.data.get("master") == n.name)
        return res

    # hosts, wires and interfaces

    def group(self, name: str) -> HostGroup:
        g = self.groups.get(name)
        if g is None:
            g = HostGroup(name=name)
            self.sess.add(g)
            self.groups[name] = g
            self.count("group")
        return g

    def host(self, sub: tuple, name: str, domain: str, typ: ThingTyp, **kw: Any) -> Host:
        h = Host(domain=domain, **{k: v for k, v in kw.items() if k != "descr"})
        th = Thing(name=name, thingtyp=typ)
        if kw.get("descr"):
            th.descr = kw["descr"]
        h.thing = th
        self.sess.add_all((th, h))
        self.hosts[sub] = h
        self.ifaces[sub] = {}
        self.count(typ.name)
        return h

    def iface(self, sub: tuple, name: str, v: dict[str, Any] | None = None) -> Interface:
        h = self.hosts[sub]
        ifs = self.ifaces[sub]
        if name in ifs:
            return ifs[name]
        v = v or {}
        where = f"{h.domain}:{name or '.'}"
        i = Interface(name=name, host=h, desc=v.get("desc"), mac=_mac(v.get("mac")))
        n, num = self.resolve_net(v.get("net"), v.get("num"))
        if v.get("net") is not None and n is None:
            self.r.skipped.append(f"iface {where}: unknown net {v['net']!r}")
        vl = self.find_vlan(n.vlan) if n is not None else None
        pv = v.get("vlan")
        if pv is not None and not isinstance(pv, bool):
            pvl = self.find_vlan(pv)
            if pvl is None:
                self.r.skipped.append(f"iface {where}: unknown VLAN {pv!r}")
            elif vl is None:
                vl = pvl
            elif pvl is not vl:
                self.r.changed.append(f"iface {where}: VLAN {pv} ignored, net is on {vl.name}")
        i.vlan = vl
        if vl is not None and num is not None:
            key = (vl.tag, num)
            if key in self.seq:
                self.r.changed.append(
                    f"iface {where}: seqnum {num} on {vl.name} already used by "
                    f"{self.seq[key]}, dropped"
                )
            else:
                self.seq[key] = where
                i.seqnum = num
                routed = {nw.name for nw in self.networks.values() if nw.vlan is vl}
                if n is not None and routed - self.family(n):
                    self.r.expanded.append(f"{where}: {', '.join(sorted(routed))}")
        elif num is not None:
            self.r.changed.append(f"iface {where}: seqnum {num} dropped, no VLAN")
        extra = {k: x for k, x in v.items() if k not in _PORT_KEYS}
        if isinstance(pv, bool):
            extra["vlan"] = pv
        if extra:
            self.r.attrs.append(f"{where}: {extra!r}")
        self.sess.add(i)
        ifs[name] = i
        self.count("interface")
        return i

    # cables

    def endpoint(self, dest: Any) -> Interface | None:
        path, *port = dest
        sub = tuple(path)
        if sub not in self.hosts:
            return None
        pname = port[0] if port else ""
        if pname not in self.ifaces[sub] and sub[0] == "host" and not port:
            return self.iface(sub, "")
        return self.ifaces[sub].get(pname)

    def cable(self, v: dict[str, Any], used: set[int]) -> None:
        a, b = self.endpoint(v.get("a", ())), self.endpoint(v.get("b", ()))

        def desc(d: Any) -> str:
            return ":".join(str(x) for x in d)

        what = f"cable {desc(v.get('a', ()))} – {desc(v.get('b', ()))}"
        if a is None or b is None:
            self.r.skipped.append(f"{what}: endpoint missing")
            return
        if id(a) in used or id(b) in used:
            self.r.skipped.append(f"{what}: endpoint already cabled")
            return
        used.update((id(a), id(b)))
        self.sess.add(Cable(iface_a=a, iface_b=b))
        self.count("cable")


def _domain(sub: tuple) -> str:
    return ".".join(str(x) for x in reversed(sub[1:]))


def import_inv(sess, items: Iterable[tuple[Path, Any]]) -> Report:
    """
    Import the KV inventory into the database session.

    Args:
        sess: The database session (see :func:`moat.db.database`).
        items: The KV entries below the inventory prefix, as
            ``(relative path, value)`` pairs.

    Returns:
        What was imported, and what needs review. Short names that are
        already taken, or longer than 40 characters, are changed.
    """
    r = Report()
    imp = _Importer(sess, r)
    by: dict[str, list[tuple[tuple, Any]]] = {}
    for path, value in items:
        sub = tuple(path)
        if sub and isinstance(value, Mapping):
            by.setdefault(str(sub[0]), []).append((sub, value))

    for sub, v in by.get("vlan", ()):
        imp.vlan(sub[1], v)
    for sub, v in by.get("net", ()):
        imp.net(sub[1], sub[2], v)
    imp.networks_()

    names = set(sess.execute(select(Thing.name)).scalars())
    t_host, t_wire = _thingtyp(sess, "host"), _thingtyp(sess, "wire")
    todo = [(sub, v, t_host) for sub, v in by.get("host", ())]
    todo += [(sub, v, t_wire) for sub, v in by.get("wire", ())]
    for sub, v, typ in todo:
        domain = str(sub[-1]) if typ is t_wire else _domain(sub)
        name = orig = (v.get("name") or domain.split(".")[0])[:40]
        n = 1
        while name in names:
            n += 1
            sfx = f"-{n}"
            name = orig[: 40 - len(sfx)] + sfx
        if name != v.get("name", name):
            r.changed.append(f"host {domain}: short name {v['name']!r} is now {name!r}")
        names.add(name)
        imp.host(sub, name, domain, typ, loc=v.get("loc"), descr=v.get("desc"))

    for sub, v in by.get("host", ()):
        direct = {k: v[k] for k in ("net", "num", "mac") if v.get(k) is not None}
        if direct:
            imp.iface(sub, "", direct)
        for pn, pv in (v.get("ports") or {}).items():
            imp.iface(sub, str(pn), pv or {})
        for g in v.get("groups") or ():
            imp.hosts[sub].groups.add(imp.group(g))
    for sub, _v in by.get("wire", ()):
        for pn in ("a", "b"):
            imp.iface(sub, pn)
    for sub, _v in by.get("group", ()):
        imp.group(str(sub[-1]))

    used: set[int] = set()
    for _sub, v in by.get("cable", ()):
        imp.cable(v, used)

    sess.flush()
    ifaces = (i for ifs in imp.ifaces.values() for i in ifs.values())
    r.counts["address"] = sum(len(i.addresses) for i in ifaces)
    return r


async def read_kv(cfg: Any) -> list[tuple[Path, Any]]:
    """
    Read the inventory from MoaT-KV.

    Args:
        cfg: The global configuration; uses ``kv`` and its ``inv.prefix``.
    """
    from moat.kv.client import open_client  # noqa: PLC0415

    prefix = cfg.kv.inv.prefix
    res = []
    async with open_client(**cfg.kv) as client:
        async for r in client.get_tree(prefix, nchain=0):
            if "value" in r:
                res.append((r.path, r.value))
    return res
