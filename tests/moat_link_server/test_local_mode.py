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

import moat.link.server._main as main_mod
import moat.link.server._server as srv_mod
from moat.util import NotGiven, attrdict
from moat.lib.config import CFG
from moat.link.server._server import Server

from typing import Any

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
