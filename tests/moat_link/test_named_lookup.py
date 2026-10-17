"""
Test the diagnostic enrichment of the named-server lookup timeout.

Bug: when a client (e.g. a link gate) is configured to connect to a
specific server by name and no announcement under that exact name exists,
the resulting ``TimeoutError`` carried no hint about the servers that
*are* announcing.  A mistyped ``server:`` — typically a host's FQDN
where the server announces under its short hostname — was thus
indistinguishable from "nothing is running".

Fix: the timeout message now lists the names of the servers found on the
backend, e.g. ``Known servers: pi-i3.``.
"""

from __future__ import annotations

import anyio
import pytest

from moat.lib.path import P
from moat.link._test import Scaffold
from moat.link.client import Link

pytestmark = pytest.mark.anyio


async def test_named_server_timeout_lists_known_servers(cfg):
    """The no-announcement timeout names the servers that ARE announcing.

    A server announcement is published under ``pi-i3`` (retained), then a
    client restricted to ``some.other.name`` must time out — and the
    error must point at the announcement that exists under a different
    name.
    """
    async with Scaffold(cfg, use_servers=True) as sf, sf.backend_(None) as bk:
        await bk.send(
            P(":R.run.service.main.server") / "pi-i3",
            {"node": "pi-i3", "link": [], "auth": {"token": "x"}},
            retain=True,
        )

        sf.cfg.client.init_timeout = 1

        with anyio.fail_after(sf.cfg.client.init_timeout + 5):
            with pytest.RaisesGroup(
                pytest.RaisesExc(
                    TimeoutError,
                    match=r"No announcement of server 'some\.other\.name'.*Known servers: pi-i3\.",
                ),
                flatten_subgroups=True,
            ):
                async with Link(sf.cfg, only="some.other.name"):
                    pass  # pragma: no cover — we must not get here


async def test_named_server_timeout_without_any_servers(cfg):
    """With no announcements at all, the message has no known-servers hint."""
    async with Scaffold(cfg, use_servers=True) as sf:
        sf.cfg.client.init_timeout = 1

        with anyio.fail_after(sf.cfg.client.init_timeout + 5):
            with pytest.RaisesGroup(
                pytest.RaisesExc(
                    TimeoutError,
                    match=r"No announcement of server 'nobody\.home' seen within \d+s\. Is it running\?",
                ),
                flatten_subgroups=True,
            ):
                async with Link(sf.cfg, only="nobody.home"):
                    pass  # pragma: no cover
