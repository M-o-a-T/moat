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
from moat.link.gate import run_gate

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
