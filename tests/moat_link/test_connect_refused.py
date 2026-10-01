"""
Regression tests for the client hanging when an announced server refuses
the TCP connection.

Bug: ``Link._run_server_link`` only called ``task_status.started()`` after a
server connection succeeded (deep inside ``_connect_run_``).  When every
attempt to reach an announced server failed with ``OSError`` — e.g.
``ConnectionRefusedError`` — ``_connect_server`` swallowed the error and the
hunt loop retried forever without ever signalling readiness.  That deadlocked
``Link.__aenter__`` (which awaits ``tg.start(self._run_server_link)``), so
``moat link host list`` hung and could not be interrupted with Ctrl-C.

Fix: the initial hunt for a server is now bounded by ``client.init_timeout``.
If no connection can be established within that budget, ``Link.__aenter__``
raises ``TimeoutError("Could not connect to … Is it running?")`` instead of
looping forever.  Once a connection is established the budget is irrelevant —
a subsequently dropped link terminates the client via ``ServerLinkLost`` as
before.
"""

from __future__ import annotations

import anyio
import pytest

from moat.lib.path import P
from moat.link._test import Scaffold
from moat.link.client import Link

pytestmark = pytest.mark.anyio


async def test_link_enter_raises_when_announced_server_refuses_connection(cfg):
    """Entering a ``Link`` must fail (not hang) when the announced server is unreachable.

    A retained server announcement pointing at a port nothing listens on is
    published to the broker.  Before the fix ``Link.__aenter__`` blocked
    forever; after the fix it raises ``TimeoutError`` within the
    ``init_timeout`` budget.  The error surfaces wrapped in an exception group
    (anyio/trio task-group semantics), so we check with ``group_contains``.
    """
    async with Scaffold(cfg, use_servers=True) as sf, sf.backend_(None) as bk:
        await bk.send(
            P(":R.run.service.main.conn"),
            {"node": "localhost", "link": [{"host": "127.0.0.1", "port": 1}]},
            retain=True,
        )

        # Tighten the init timeout so the test fails fast on regressions.
        sf.cfg.client.init_timeout = 2
        budget = sf.cfg.client.init_timeout + 3

        with anyio.fail_after(budget):
            with pytest.RaisesGroup(TimeoutError, flatten_subgroups=True):
                async with Link(sf.cfg, name="dead_srv"):
                    pass  # pragma: no cover — we must not get here


async def test_link_enter_does_not_hang_past_init_timeout(cfg):
    """``Link.__aenter__`` must return within ~``init_timeout`` even with no reachable server.

    A broader guard against the original hang: the whole enter attempt must
    complete (by raising) well inside a fixed wall-clock budget, regardless of
    the (possibly longer) connect-backoff settings.
    """
    async with Scaffold(cfg, use_servers=True) as sf, sf.backend_(None) as bk:
        await bk.send(
            P(":R.run.service.main.conn"),
            {"node": "localhost", "link": [{"host": "127.0.0.1", "port": 1}]},
            retain=True,
        )

        sf.cfg.client.init_timeout = 2
        # Wall-clock ceiling: init_timeout + a generous slack.  Before the
        # fix this trips (hang); after the fix the inner TimeoutError fires
        # first.
        with anyio.fail_after(sf.cfg.client.init_timeout + 5):
            with pytest.RaisesGroup(TimeoutError, flatten_subgroups=True):
                async with Link(sf.cfg, name="dead_srv2"):
                    pass  # pragma: no cover
