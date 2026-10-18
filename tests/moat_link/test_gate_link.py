"""The link gate's remote side must not use the local client's socket.

The gate builds its remote Link from the local configuration. Settings
like ``client.path`` (and ``client.local_only``) point at the *local*
server; inheriting them connects the "remote" side to our own server,
syncing the subtree with itself.
"""

from __future__ import annotations

import anyio
import copy
import pytest

from moat.util import attrdict
from moat.lib.path import P
from moat.link._test import Scaffold
from moat.link.exceptions import RemoteDead
from moat.link.gate import run_gate
from moat.link.meta import MsgMeta

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from moat.lib.path import Path
    from moat.link.client import LinkSender

pytestmark = pytest.mark.anyio

TIMEOUT = 10  #: max seconds to wait for the gate to converge


async def _d_get(link: LinkSender, path: Path, timeout: float = TIMEOUT) -> Any:
    """Fetch @path once it exists on the server behind @link."""
    deadline = anyio.current_time() + timeout
    while True:
        try:
            return await link.d_get(path)
        except KeyError:
            if anyio.current_time() >= deadline:
                raise AssertionError(f"No data at {path!s} on the far side") from None
            await anyio.sleep(0.1)


async def test_gate_remote_skips_local_socket(cfg, tmp_path):
    """A socket-configured client's link gate must reach the remote server.

    Two servers on two separate brokers: the local client talks to
    ``SRVA`` via its Unix socket (``client.path`` + ``local_only``), the
    gate syncs ``x`` between them. If the gate's remote Link inherited the
    local socket, it would connect to ``SRVA`` and the data on ``SRVB``
    would never arrive.
    """
    gcfg = attrdict(
        driver="link",
        src=P("x"),
        server="SRVB",
        delay=0.1,
    )

    async with (
        Scaffold(copy.deepcopy(cfg), use_servers=True) as sf_a,
        Scaffold(copy.deepcopy(cfg), use_servers=True) as sf_b,
    ):
        # The local server listens on TCP (for its announcement) and on a
        # Unix socket, which the local client is locked onto.
        sock = str(tmp_path / "srv_a.sock")
        await sf_a.server(
            cfg={
                "server": {
                    "ports": {
                        "main": {"host": "127.0.0.1", "port": 0},
                        "local": {"port": sock},
                    }
                }
            },
            name="SRVA",
            init="TEST",
        )
        # The remote server is on the other broker, TCP only.
        await sf_b.server(name="SRVB", init="TEST")

        # The remote Link must use SRVB's broker, not the local one.
        gcfg["backend"] = dict(sf_b.cfg.backend)

        async with (
            sf_a.client_(cfg={"client": {"path": sock, "local_only": True}}) as ca,
            sf_b.client_() as cb,
        ):
            # Distinct data on each side, below the gated path.
            await ca.d_set(P("x.a"), 1)
            await ca.i_sync()
            await cb.d_set(P("x.b"), 2)
            await cb.i_sync()

            await ca.d_set(P("gate.socktest"), gcfg)
            await ca.i_sync()

            async with anyio.create_task_group() as tg:
                await tg.start(run_gate, sf_a.cfg, ca, P("gate.socktest"))

                # The gate is up (initial sync done): both sides must
                # have converged. With the bug, "x.b" never crosses over
                # because the "remote" side is the local server.
                assert await _d_get(ca, P("x.b")) == 2
                assert await _d_get(cb, P("x.a")) == 1

                tg.cancel_scope.cancel()


async def test_gate_remote_root_override(cfg):
    """The gate's ``root`` key repoints the remote Link at the remote root.

    Two servers on two brokers use different link roots (``ra`` and
    ``rb``). The gate on the ``ra`` side declares ``root: rb`` so its
    remote Link publishes/subscribes below the remote root. Without the
    override (or with a frozen global Root) the remote side would use
    the local root and nothing would cross over.
    """
    gcfg = attrdict(
        driver="link",
        src=P("x"),
        server="SRVD",
        delay=0.1,
        root=P("rb"),
    )

    async with (
        Scaffold(copy.deepcopy(cfg), use_servers=True, root=P("ra")) as sf_a,
        Scaffold(copy.deepcopy(cfg), use_servers=True, root=P("rb")) as sf_b,
    ):
        await sf_a.server(name="SRVC", init="TEST")
        await sf_b.server(name="SRVD", init="TEST")

        # The remote Link must use SRVD's broker, not the local one.
        gcfg["backend"] = dict(sf_b.cfg.backend)

        async with (
            sf_a.client_() as ca,
            sf_b.client_() as cb,
        ):
            # Distinct data on each side, below the gated path.
            await ca.d_set(P("x.a"), 1)
            await ca.i_sync()
            await cb.d_set(P("x.b"), 2)
            await cb.i_sync()

            await ca.d_set(P("gate.roottest"), gcfg)
            await ca.i_sync()

            async with anyio.create_task_group() as tg:
                await tg.start(run_gate, sf_a.cfg, ca, P("gate.roottest"))

                # The gate is up (initial sync done): both sides must
                # have converged across the different roots.
                assert await _d_get(ca, P("x.b")) == 2
                assert await _d_get(cb, P("x.a")) == 1

                tg.cancel_scope.cancel()


async def test_gate_remote_announcement_reports_up(cfg):
    """The gate's remote-side announcement flips to ``up: True`` when running.

    The link gate announces itself on the remote server (so operators can
    see that a gate is syncing this subtree).  The announcement must
    report ``up: True`` once the initial sync has completed, not stay
    ``up: False`` forever (which also spams "did not (yet?) start"
    warnings from ``SetReady.wait_sr``).
    """
    gcfg = attrdict(
        driver="link",
        src=P("x"),
        server="SRVF",
        delay=0.1,
    )

    async with (
        Scaffold(copy.deepcopy(cfg), use_servers=True) as sf_e,
        Scaffold(copy.deepcopy(cfg), use_servers=True) as sf_f,
    ):
        await sf_e.server(name="SRVE", init="TEST")
        await sf_f.server(name="SRVF", init="TEST")
        gcfg["backend"] = dict(sf_f.cfg.backend)

        async with (
            sf_e.client_() as ce,
            sf_f.client_() as cf,
        ):
            await ce.d_set(P("x.a"), 1)
            await ce.i_sync()

            await ce.d_set(P("gate.anntest"), gcfg)
            await ce.i_sync()

            async with anyio.create_task_group() as tg:
                await tg.start(run_gate, sf_e.cfg, ce, P("gate.anntest"))

                # The gate is up: the remote server must see its
                # announcement with up=True (and "running" as the value).
                deadline = anyio.current_time() + TIMEOUT
                while True:
                    ann = await cf.d_get(P("run.host.gate.anntest"))
                    if ann.get("up") and ann.get("value") == "running":
                        break
                    if anyio.current_time() >= deadline:
                        raise AssertionError(f"Remote gate announcement not up: {ann!r}") from None
                    await anyio.sleep(0.1)

                tg.cancel_scope.cancel()


async def test_gate_live_update_across_roots(cfg):
    """Post-startup updates must land at the right remote path.

    The gate's local ``Watcher`` parses raw MQTT topics by stripping the
    length of the watched path.  That presumes the topic was collapsed
    against the ambient ``Root`` — but inside the gate the ambient root
    belongs to the *remote* Link, so local topics didn't collapse and
    live updates were spliced wrongly (e.g. ``x.rb.x.a`` instead of
    ``x.a``).  Initial sync (RPC-based) was unaffected.
    """
    gcfg = attrdict(
        driver="link",
        src=P("x"),
        server="SRVH",
        delay=0.1,
        root=P("rb"),
    )

    async with (
        Scaffold(copy.deepcopy(cfg), use_servers=True, root=P("ra")) as sf_g,
        Scaffold(copy.deepcopy(cfg), use_servers=True, root=P("rb")) as sf_h,
    ):
        await sf_g.server(name="SRVG", init="TEST")
        await sf_h.server(name="SRVH", init="TEST")
        gcfg["backend"] = dict(sf_h.cfg.backend)

        async with (
            sf_g.client_() as cg,
            sf_h.client_() as ch,
        ):
            # Seed data BEFORE the gate starts, so the initial sync has
            # something to carry over.
            await cg.d_set(P("x.seed"), 11)
            await cg.i_sync()

            await cg.d_set(P("gate.livetest"), gcfg)
            await cg.i_sync()

            async with anyio.create_task_group() as tg:
                await tg.start(run_gate, sf_g.cfg, cg, P("gate.livetest"))

                # Initial sync carried the seed over.
                assert await _d_get(ch, P("x.seed")) == 11

                # Now a LIVE update, after the gate settled: it must
                # arrive at x.live on the remote — and nowhere else.
                await cg.d_set(P("x.live"), 22)
                assert await _d_get(ch, P("x.live")) == 22

                # The corrupted-path variant must NOT exist.
                try:
                    d = await ch.d_get(P("x.rb.x.live"))
                except KeyError:
                    pass
                else:
                    raise AssertionError(f"Corrupted path exists: x.rb.x.live = {d!r}")

                tg.cancel_scope.cancel()


async def test_gate_send_wraps_source_metadata(cfg):
    """Sent data must carry the source metadata in ``gw``.

    The gate wraps the far side's metadata in a ``gw`` key when copying
    *to* the source (``_set_src``); the link gate must do the same when
    copying *to* the remote (``set_dst``), so the receiving side can tell
    where the data originally came from.
    """
    gcfg = attrdict(
        driver="link",
        src=P("x"),
        server="SRVK",
        delay=0.1,
    )

    async with (
        Scaffold(copy.deepcopy(cfg), use_servers=True) as sf_j,
        Scaffold(copy.deepcopy(cfg), use_servers=True) as sf_k,
    ):
        await sf_j.server(name="SRVJ", init="TEST")
        await sf_k.server(name="SRVK", init="TEST")
        gcfg["backend"] = dict(sf_k.cfg.backend)

        async with (
            sf_j.client_() as cj,
            sf_k.client_() as ck,
        ):
            # Source data with distinctive metadata.
            await cj.d_set(P("x.a"), 1, meta=MsgMeta(origin="TESTSRC"))
            await cj.i_sync()

            await cj.d_set(P("gate.gwtest"), gcfg)
            await cj.i_sync()

            async with anyio.create_task_group() as tg:
                await tg.start(run_gate, sf_j.cfg, cj, P("gate.gwtest"))

                # The remote copy must carry the source's origin in "gw".
                deadline = anyio.current_time() + TIMEOUT
                while True:
                    try:
                        _, m = await ck.d_get(P("x.a"), meta=True)
                    except KeyError:
                        m = None
                    if m is not None:
                        gw = m.kw.get("gw", None)
                        if gw is not None and gw.origin == "TESTSRC":
                            break
                    if anyio.current_time() >= deadline:
                        raise AssertionError(f"Source metadata lost: {m!r}") from None
                    await anyio.sleep(0.1)

                tg.cancel_scope.cancel()


async def test_gate_ping_dead_remote(cfg, monkeypatch):
    """A link gate with ``ping`` detects a dead remote and stops.

    The gate probes the remote server with ``i.stamp`` calls. Hanging the
    remote server's stamps (network-dead remote: the broker still works,
    so no MQTT error ever arrives) must make the gate raise ``RemoteDead``
    after ``miss`` consecutive timeouts, ending the gate so its
    announcements go away.
    """
    gcfg = attrdict(
        driver="link",
        src=P("x"),
        server="SRVP",
        delay=0.1,
        ping=0.2,
        miss=2,
    )

    async with (
        Scaffold(copy.deepcopy(cfg), use_servers=True) as sf_l,
        Scaffold(copy.deepcopy(cfg), use_servers=True) as sf_r,
    ):
        await sf_l.server(name="SRVL", init="TEST")
        srv_r = await sf_r.server(name="SRVP", init="TEST")
        gcfg["backend"] = dict(sf_r.cfg.backend)

        async with (
            sf_l.client_() as cl,
            sf_r.client_() as cr,
        ):
            await cl.d_set(P("x.a"), 1)
            await cl.i_sync()

            await cl.d_set(P("gate.pingtest"), gcfg)
            await cl.i_sync()

            async with anyio.create_task_group() as tg:

                async def _gate(*, task_status) -> None:
                    """Run the gate; its death by ``RemoteDead`` is the point."""
                    try:
                        await run_gate(sf_l.cfg, cl, P("gate.pingtest"), task_status=task_status)
                    except* RemoteDead:
                        pass

                await tg.start(_gate)

                # The gate is up and synced.
                assert await _d_get(cr, P("x.a")) == 1

                # Kill the remote server's responsiveness: stamps hang.
                async def _hang(*a, **k):  # noqa: ARG001
                    await anyio.sleep_forever()

                monkeypatch.setattr(srv_r, "new_stamp", _hang)

                # The gate must die: its remote-side announcement goes away.
                deadline = anyio.current_time() + 10
                while True:
                    try:
                        await cr.d_get(P("run.host.gate.pingtest"))
                    except KeyError:
                        break
                    if anyio.current_time() >= deadline:
                        raise AssertionError("Gate survived its dead remote") from None
                    await anyio.sleep(0.1)

                tg.cancel_scope.cancel()
