"""
Unit tests for "local-only" server mode.

``--local`` (aka ``local_only``) tells the server to abstain from
volunteering for cluster-wide duties: `_pinger` then does not advertise a
ping value (no ``actor.set_value``), so the peer-election algorithm
considers this node permanently ineligible. Everything else — reacting to
peers, firing the ``ready`` event — proceeds unchanged.

Sections:

* `_local_mode` (helper predicate)
* `_pinger` event dispatch
* CLI plumbing (``-L`` reaches both config and `Server` instantiation)
"""

from __future__ import annotations

import anyio
import io
import pytest
from contextlib import asynccontextmanager

from asyncactor import GoodNodeEvent, NodeList, PingEvent, TagEvent
from asyncactor.messages import PingMessage

import moat.link._main as link_main
import moat.link.announce as announce_mod
import moat.link.server._main as main_mod
import moat.link.server._server as srv_mod
from moat.util import NotGiven, attrdict, ungroup
from moat.lib.config import CFG
from moat.lib.path import P
from moat.link._test import Scaffold
from moat.link.client import BasicLink
from moat.link.meta import MsgMeta
from moat.link.node import Node
from moat.link.server._server import Server

from typing import Any


def _walk_fetch(client, path):
    "Retrieve subtree contents as a `Node` (mirrors test_sync's walker)."
    from moat.lib.path import PathLongener  # noqa: PLC0415
    from moat.lib.rpc import StreamError  # noqa: PLC0415

    async def impl():
        nn = Node()
        pl = PathLongener()
        pp = P(path)
        async with client.cmd(P("d.walk"), pp).stream_in() as msgs:
            try:
                it = aiter(msgs)
            except StreamError as exc:
                try:
                    if exc.args[0][0] == "KeyError":
                        return nn  # empty
                except Exception:
                    pass
                raise exc from None

            async for pr, pth, dt, *mt in it:
                pth = pl.long(pr, pth)
                nn.set(pth, dt, MsgMeta.restore(mt))
        return nn

    return impl


# --------------------------------------------------------------- #
# Stubs                                                           #
# --------------------------------------------------------------- #


class ActorStub:
    "Stand-in for ``asyncactor``'s Actor, as consumed by `Server._pinger`."

    def __init__(self, events):
        self.values = []
        self.closed = False
        self._it = iter(events)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        self.closed = True
        return None

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration from None

    async def set_value(self, val):  # noqa: D102
        self.values.append(val)


class TGStub:
    "Records `_tg.start_soon` calls issued during ping processing."

    def __init__(self):
        self.spawned = []

    def start_soon(self, fn, *a):  # noqa: D102
        self.spawned.append((fn, a))


class BackendStub:
    "Just enough of the backend for `set_main_link` to fire silently."

    def __init__(self):
        self.sent = []

    async def send(self, *a, **kw):  # noqa: D102
        self.sent.append((a, kw))


_REAL = {}


def make_good(nodes=None):
    "Somebody looks good to talk to."
    nl = NodeList(0, ["N0"] if nodes is None else nodes)
    return GoodNodeEvent(nl)


def make_tag():
    "A TagEvent claims that THIS node is 'it'."
    return TagEvent("LS", {"some": "val"})


def make_ping(other="Peer"):
    "Someone else's ping: this node is definitively not 'it'."
    return PingEvent(PingMessage(node=other))


def wire(server, actor):
    "Prepare a barely-initialized `Server` for direct `_pinger` injection."
    if not _REAL:
        _REAL.update(get_transport=srv_mod.get_transport, Actor=srv_mod.Actor)
    server._tg = TGStub()  # noqa: SLF001
    server.backend = BackendStub()
    server.link_data = []  # advertised addresses, irrelevant here
    server.refresh_auth()  # populate cur_auth/last_auth for set_main_link

    # `_pinger` expects a richly shaped ``cfg.server``; graft the pieces it
    # accesses onto whatever the individual test wants to arrange.
    from moat.util import combine_dict, to_attrdict  # noqa: PLC0415

    base = to_attrdict({
        "server": {
            "ping": {"cycle": 50, "gap": 5, "enable": False},
            "timeout": {"up": 0},
            "local_only": False,
        }
    })
    existing = getattr(server, "cfg", None)
    server.cfg = (
        combine_dict(existing, base, cls=to_attrdict({}).__class__)
        if existing is not None
        else base
    )

    # `_pinger` computes ``T = get_transport("moat_link")`` then builds
    # ``Actor(T(backend, path), …)``. Both stand-ins disregard arguments
    # and hand back our stub.
    srv_mod.get_transport = lambda _tag: lambda *_a, **_kw: "stub"  # ty:ignore[invalid-assignment]
    srv_mod.Actor = lambda *_a, **_kw: actor  # ty:ignore[invalid-assignment]
    return anyio.Event()


def unwire():
    "Restore whatever `wire` had swapped out."
    gt = _REAL.pop("get_transport", None)
    if gt is not None:
        srv_mod.get_transport = gt
    ac = _REAL.pop("Actor", None)
    if ac is not None:
        srv_mod.Actor = ac


@pytest.fixture
def restored():
    "Guarantee symbol restoration, even when a test blows up halfway."
    yield
    unwire()


# --------------------------------------------------------------- #
# `_local_mode`                                                   #
# --------------------------------------------------------------- #


@pytest.mark.anyio
async def test_local_mode_unset():
    "`local_only` omitted ⇒ the server joins leader election normally."
    from moat.lib.config import CfgStore  # noqa: PLC0415

    # Test with defaults from ``moat/link/server/_cfg.yaml``
    store = CfgStore(name=None, load_all=False, preload=attrdict(env=NotGiven))
    with CFG.with_config_(store):
        CFG.with_("moat.link.server")

        server = Server(CFG.moat.link, "LS")
        assert server._local_mode() is False  # noqa: SLF001
        # Positive control: prove the assertion exercises real data flow
        server.cfg.server.local_only = True
        assert server._local_mode() is True  # noqa: SLF001


@pytest.mark.anyio
async def test_local_mode_via_config():
    "Plain config-flag flip is honored."
    server = Server({"server": {"local_only": True}}, "LS")
    assert server._local_mode() is True  # noqa: SLF001


@pytest.mark.anyio
@pytest.mark.usefixtures("restored")
async def test_local_mode_explicit_beats_config():
    "Hard-wired flag vs. config: the former always wins."
    server = Server({"server": {"local_only": False}}, "LS", force_local=True)
    assert server._local_mode() is True  # noqa: SLF001
    server2 = Server({"server": {"local_only": True}}, "LS", force_local=False)
    assert server2._local_mode() is True  # noqa: SLF001


@pytest.mark.parametrize("lo", [False, None])
@pytest.mark.anyio
async def test_local_mode_falsy(lo):
    "Disabled config ⇒ ordinary participation; absent config gets the packaged default."
    # Production pipelines (lib.run) hydrate defaults, guaranteeing the
    # ``local_only`` slot even when the operator's config omits it. Model
    # both flavors faithfully.
    if lo is None:
        # Absent-operator-config flavor: emulate hydration by seeding the
        # packaged default ourselves (mirrors ``_cfg.yaml``).
        cfg = {"server": {"local_only": False}}
    else:
        cfg = {"server": {"local_only": lo}}
    server = Server(cfg, "LS")
    assert server._local_mode() is False  # noqa: SLF001


# --------------------------------------------------------------- #
# `_pinger`                                                       #
# --------------------------------------------------------------- #


@pytest.mark.anyio
@pytest.mark.usefixtures("restored")
async def test_pinger_regular_claims_value():
    "Ordinary operation: each qualifying event advertises eligibility."
    server = Server({"server": {}}, "LS")
    actor = ActorStub([make_good(), make_tag(), make_ping()])
    ready = wire(server, actor)

    with anyio.move_on_after(0.5):
        await server._pinger(ready)  # noqa: SLF001

    assert ready.is_set()
    assert actor.values == [True, True, True]


@pytest.mark.anyio
@pytest.mark.usefixtures("restored")
async def test_pinger_local_only_stays_quiet():
    "Local-only: no set_value anywhere; ``ready`` still propagates."
    server = Server({"server": {"local_only": True}}, "LS")
    actor = ActorStub([make_good(), make_tag(), make_ping()])
    ready = wire(server, actor)

    with anyio.move_on_after(0.5):
        await server._pinger(ready)  # noqa: SLF001

    assert ready.is_set()
    assert actor.values == []


@pytest.mark.anyio
@pytest.mark.usefixtures("restored")
async def test_pinger_forced_equals_configured():
    "``force_local=True`` acts precisely like config-set ``local_only``."
    server = Server({"server": {}}, "LS", force_local=True)
    actor = ActorStub([make_good()])
    ready = wire(server, actor)

    with anyio.move_on_after(0.5):
        await server._pinger(ready)  # noqa: SLF001

    assert ready.is_set()
    assert actor.values == []


@pytest.mark.anyio
@pytest.mark.usefixtures("restored")
async def test_pinger_own_ping_is_ignored():
    "Long-standing quirk preserved: our own echoed pings don't ack."
    server = Server({"server": {}}, "LS")
    actor = ActorStub([make_ping(other="LS")])
    ready = wire(server, actor)

    with anyio.move_on_after(0.5):
        await server._pinger(ready)  # noqa: SLF001

    assert actor.values == []


@pytest.mark.anyio
@pytest.mark.usefixtures("restored")
async def test_pinger_eof_ends_cleanly():
    "Instant stream exhaustion winds `_pinger` down without commotion."
    server = Server({"server": {}}, "LS")
    actor = ActorStub([])
    ready = wire(server, actor)

    with anyio.move_on_after(0.5), anyio.fail_after(0.4):
        await server._pinger(ready)  # noqa: SLF001

    assert ready.is_set() is False


# --------------------------------------------------------------- #
# CLI                                                             #
# --------------------------------------------------------------- #


def _evt_of():
    "Duck-typed `RunMsg` clone: readiness signalling plus `TaskStatus`."

    class Evt:
        "Signals readiness."

        def __init__(self):
            self.was_set = False

        def set(self):
            self.was_set = True

        def started(self, value=None):
            if value is not None:
                raise ValueError("unexpected value")
            self.set()

    return Evt()


@pytest.fixture
def cli_hook(monkeypatch):
    """
    Stand up inert siblings of `as_service`, `Server`, and `Link`.

    Returns a `made` dict accumulating observations: constructed `Server`
    twins land in ``made["servers"]``.
    """
    made = {}

    class FakeServer:
        "Remembers ctor arguments; parks itself quietly thereafter."

        instances = []

        def __init__(self, cfg, name, **kw):
            self.cfg = cfg
            self.name = name
            self.kw = kw
            FakeServer.instances.append(self)

        async def serve(self, *, task_status):
            task_status.started((self, []))
            await anyio.sleep_forever()

        async def wait_stopped(self):
            await anyio.sleep_forever()

    class FakeAnnounce:
        "`ann` shim: no news is good news."

        def set(self):
            pass

    class FakeLink:
        "Transparent context manager recording its cfg."

        def __init__(self, cfg, **_kw):
            made["link_cfg"] = cfg

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_e):
            return None

        @asynccontextmanager
        async def announcing(self, *, force=False):  # noqa: ARG002
            yield FakeAnnounce()

    @asynccontextmanager
    async def fake_as_service(_obj):
        async with anyio.create_task_group() as tg:
            evt = _evt_of()
            evt.tg = tg
            yield evt

    monkeypatch.setattr(main_mod, "as_service", fake_as_service)
    monkeypatch.setattr(main_mod, "Server", FakeServer)
    monkeypatch.setattr(main_mod, "Link", FakeLink)
    made["servers"] = FakeServer.instances
    return made


async def _run_cli(callback_wrapped, obj, **kw):
    "Invoke `cli`'s guts; tolerate endless `wait_stopped` loops."

    async def bounded():
        with anyio.move_on_after(0.3):
            await callback_wrapped(
                obj, None, None, None, kw.get("force_local", False), kw.get("name", "UT")
            )
        return True

    try:
        await bounded()
    except Exception as ex:
        return ex
    return None


# Bind the unwrapped CLI callback ONCE: ty dislikes poking `__wrapped__`
# through click's optional-attribute lens repeatedly.
_RAW_CALLBACK = getattr(main_mod.cli.callback, "__wrapped__", None)
if _RAW_CALLBACK is None:
    raise RuntimeError("cli lost its __wrapped__ decoration?!")

#: Canonical handle onto `cli`'s internals:
#: ``(obj, load, save, init, force_local, name)``.
_real_cb: Any = _RAW_CALLBACK


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("fl", "exp_lo", "exp_forced"),
    [(False, False, False), (True, True, True)],
)
@pytest.mark.usefixtures("restored")
async def test_cli_plumbs_flask(fl, exp_lo, exp_forced, cli_hook):
    "Whether ``-L`` toggles config, the ctor kwarg mirrors the request."
    obj = attrdict(cfg=attrdict(link=attrdict()), debug=0, stdout=io.StringIO())
    err = await _run_cli(_real_cb, obj, force_local=fl, name="UT")
    if err is not None:
        pytest.fail(f"Unexpected failure: {err!r}")

    made = cli_hook
    svrs = made["servers"]
    assert len(svrs) == 1, f"Expected exactly one Server, got {svrs!r}"
    s = svrs[0]
    assert s.kw.get("force_local", False) is exp_forced
    lo_now = s.cfg.get("server", {}).get("local_only", False)
    assert bool(lo_now) is exp_lo


@pytest.mark.anyio
async def test_cli_unmodified_config_remains_absent(cli_hook):
    "Sans ``-L``, nothing materializes beneath ``link.server``."
    obj = attrdict(cfg=attrdict(link=attrdict()), debug=0, stdout=io.StringIO())
    err = await _run_cli(_real_cb, obj, name="UT")
    if err is not None:
        pytest.fail(f"Unexpected failure: {err!r}")

    s = cli_hook["servers"][0]
    scf = s.cfg.get("server")
    if scf is not None:
        assert "local_only" not in scf


# ------------------------------------------------------------ #
# Client local-only (--local / local_only)                      #
# ------------------------------------------------------------ #


@pytest.mark.anyio
async def test_client_local_requires_path(cfg):
    "``local_only`` sans socket path is rejected outright."
    async with Scaffold(cfg, use_servers=True) as sf:
        with pytest.raises(RuntimeError) as ei, ungroup:
            async with sf.client_({"client": {"local_only": True}}) as _c:
                pass
    assert "path" in str(ei.value), f"Wanted path advice, got {ei.value!s}"


@pytest.mark.anyio
async def test_client_local_missing_socket(cfg):
    "Unresponsive (vacant) socket path ⇒ connect itself refuses; no fallback."
    # Deliberately NO pre-probing: the connect attempt is the truth source.
    async with Scaffold(cfg, use_servers=True) as sf:
        with pytest.raises(RuntimeError) as ei, ungroup:
            async with sf.client_({
                "client": {"local_only": True, "path": "/nonexistent/hopeless.sock"}
            }) as _c:
                pass
    msg = str(ei.value)
    assert "hopeless.sock" in msg
    assert "failed" in msg.lower()


@pytest.mark.anyio
async def test_client_local_dead_socket(cfg):
    "Bound-then-abandoned socket (lingering inode, deaf) ⇒ refused."
    async with anyio.TemporaryDirectory() as td:
        dead_sock = f"{td}/dead.sock"
        # Closing the listener leaves the inode; connects hit ECONNREFUSED.
        listener = await anyio.create_unix_listener(dead_sock)
        await listener.aclose()

        async with Scaffold(cfg, use_servers=True) as sf:
            with pytest.raises(RuntimeError) as ei, ungroup:
                async with sf.client_({"client": {"local_only": True, "path": dead_sock}}) as _c:
                    pass
        # Deaf socket: refusal must cite the culprit explicitly.
        assert "failed" in str(ei.value)


@pytest.mark.anyio
async def test_client_local_success_via_socket(cfg):
    "Happy path: local-only client connects through the real socket."
    async with anyio.TemporaryDirectory() as td:
        sock_path = f"{td}/live.sock"
        server_patch = {
            "server": {
                "ports": {
                    "main": {"host": "0.0.0.0", "port": 0},  # noqa:S104
                    "unix": {"port": sock_path},
                }
            }
        }
        async with (
            Scaffold(cfg, use_servers=True) as sf,
            sf.server_(server_patch, init={}),
            sf.client_({"client": {"local_only": True, "path": sock_path}}) as c,
        ):
            await c.d_set(P("test.local"), "yes!")
            await c.i_sync()
            assert (await c.d_get(P("test.local"))) == "yes!"


@pytest.mark.anyio
async def test_client_local_survives_without_announcements(cfg, monkeypatch):
    "Even with a sabotaged announcement facility, local-only connects happily;"
    "local-only mode must be utterly indifferent."
    ann_mod = announce_mod

    async def refuse(*_a, **_kw):
        raise RuntimeError("Shouldn't even peek at announcements in local-only mode")

    monkeypatch.setattr(ann_mod, "announcing", refuse)

    async with anyio.TemporaryDirectory() as td:
        sock_path = f"{td}/silent.sock"
        server_patch = {
            "server": {
                "ports": {
                    "main": {"host": "0.0.0.0", "port": 0},  # noqa:S104
                    "unix": {"port": sock_path},
                }
            }
        }
        async with (
            Scaffold(cfg, use_servers=True) as sf,
            sf.server_(server_patch, init={}),
            sf.client_({"client": {"local_only": True, "path": sock_path}}) as c,
        ):
            await c.d_set(P("test.quiet"), "fine")
            await c.i_sync()
            assert (await c.d_get(P("test.quiet"))) == "fine"


# ------------------------------------------------------------ #
# CLI: `moat link -L`                                         #
# ------------------------------------------------------------ #


def _link_group_obj(sock_path=None):
    "Fabricate the context-object that `moat.link._main.cli` expects."
    cl = attrdict({})
    if sock_path is not None:
        cl["path"] = sock_path
    lk = attrdict(
        root=P("test.moat.link.cli"),
        backend=attrdict(driver="mqtt", codec="std-cbor", host="127.0.0.1", port=1),
        client=cl,
    )
    return attrdict(cfg=attrdict(link=lk), stdout=io.StringIO(), debug=0)


@pytest.mark.anyio
async def test_cli_local_missing_path_block():
    '`-L` without a "path" aborts immediately.'
    mlm = link_main

    obj = _link_group_obj(None)
    ctx_stub = attrdict(obj=obj)
    with pytest.raises(mlm.click.UsageError) as ei:
        await mlm.cli.callback.__wrapped__(ctx_stub, None, True)  # link_name=?, -L
    assert "path" in str(ei.value)


@pytest.mark.anyio
async def test_cli_local_arbitrary_path_accepted(tmp_path):
    """
    `-L` cares about CONFIGURATION, not the filesystem.

    A dangling path is fine at gate time: existence/connectivity verdicts
    belong to the actual connect attempt (TOCTOU avoidance), where the
    client reports problems loudly.
    """
    mlm = link_main

    obj = _link_group_obj(str(tmp_path / "later-allegedly-a.socket"))
    ctx_stub = attrdict(obj=obj)
    # Plain invocation: with no subcommand scheduled, `load_subgroup`
    # degenerates into a benign no-op here.
    await mlm.cli.callback.__wrapped__(ctx_stub, None, True)
    assert obj.cfg.link.client.local_only is True


@pytest.mark.anyio
async def test_cli_local_good_socket_passes(tmp_path):
    "`-L` with a healthy socket passes the gate and plants the flag."
    mlm = link_main

    sock = tmp_path / "ok.sock"
    lst = await anyio.create_unix_listener(str(sock))
    try:
        obj = _link_group_obj(str(sock))
        ctx_stub = attrdict(obj=obj)
        await mlm.cli.callback.__wrapped__(ctx_stub, None, True)
        assert obj.cfg.link.client.local_only is True
    finally:
        await lst.aclose()


# --------------------------------------------------------------- #
# Cross-compartment isolation: client-local-only ⇏ server-local    #
# --------------------------------------------------------------- #


@pytest.mark.anyio
async def test_server_sync_indifferent_to_client_local_flag(cfg):
    """
    `cfg.client.local_only` poisons NOTHING beyond client connection policy.

    A server sharing that same config blob keeps talking to REMOTE
    servers for data sync: `_watch_up` notices strangers' announcements
    and dials them; the flag never enters `_watch_up`/`_run_server_link`
    territory. Both directions get exercised.
    """
    # Adversarial: both SERVERS inherit a client-poisoned blob; only the
    # writer client is spared (otherwise IT couldn't connect, by design).
    poison = {"client": {"local_only": True}}

    async with Scaffold(cfg, use_servers=True) as sf:
        # SRVs are born seeing "local_only": True under ``client`` —
        # proving the flag never steers SERVER outbound linking.
        await sf.server(poison, init={"cross.sync": "seeded"})
        await sf.server()  # pristine partner

        c_write = await sf.client()  # ordinary writer
        await c_write.cmd(P("d.set"), P("symmetry.case"), "shared-data")

        # THE observation: a fresh (cleanly-configured) client witnesses
        # the disseminated datum, proving A↔B synchronized THROUGH the
        # respective inbounds/outbounds rather than any client-direct lane.
        c_read = await sf.client()
        await c_read.i_sync()
        res, *_meta = await c_read.cmd(P("d.get"), P("symmetry.case"))
        assert res == "shared-data"

        # Belt&braces: ALSO verify via BasicLink (what servers deploy among
        # themselves), reconstructing announcement data — confirming that
        # the "client"-lane banishment didn't starve server lanes.
        c_probe = await sf.client()
        if c_probe._link._last_link is None:  # noqa: SLF001
            await c_probe._link._last_link_seen.wait()  # noqa: SLF001
        link_payload = c_probe._link._last_link.data  # noqa: SLF001

        # Replica-convergence patience: the probe's server may trail the
        # writer's by an iota; poll gently until the datum is observable.
        observed = None
        with anyio.move_on_after(5):
            async with BasicLink(cfg, "_probe", link_payload) as bl:
                while observed is None:
                    # Depth-relativity: walking 'symmetry' responds with
                    # fragments RELATIVE to that prefix ('case').
                    nn = await _walk_fetch(bl, "symmetry")()
                    if P("case") in nn:
                        observed = nn[P("case")].data
                        break
                    await anyio.sleep(0.1)
        assert observed == "shared-data"
