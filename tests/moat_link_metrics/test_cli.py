"""End-to-end tests for ``moat.link.metrics`` CLI commands.

The CLI is invoked through :py:meth:`moat.link._test.Scaffold.run` so the
full ``asyncclick`` decorator stack is exercised.
"""

from __future__ import annotations

import pytest

import moat.link.metrics  # noqa:F401 - register cfg
from moat.lib.path import P
from moat.link._test import Scaffold
from moat.src.test import raises as _raises

pytestmark = pytest.mark.anyio


async def test_server_lifecycle(cfg):
    """Add, set, list and delete a server via the CLI."""

    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as c,
    ):
        prefix = cfg.link.metrics.prefix

        await sf.run("link metrics srv1 add -b akumuli -h example.com -p 8282")
        await c.i_sync()

        data = await c.d_get(prefix + P("srv1"))
        assert data == {"backend": "akumuli", "server": {"host": "example.com", "port": 8282}}

        # second add without --force fails
        import asyncclick as click  # noqa:PLC0415

        with _raises(click.UsageError) as r:
            await sf.run("link metrics srv1 add -b akumuli -h other -p 8000")
        assert r.value is not None
        assert "already exists" in r.value.format_message().lower()

        # set updates fields
        await sf.run("link metrics srv1 set -h newhost")
        await c.i_sync()
        data = await c.d_get(prefix + P("srv1"))
        assert data["server"]["host"] == "newhost"
        assert data["server"]["port"] == 8282
        assert data["backend"] == "akumuli"

        # listing: '-' enumerates servers
        r = await sf.run("link metrics -")
        assert "srv1" in r.stdout

        # delete is always recursive: child entries go away too
        await c.d_set(
            prefix + P("srv1.child"),
            {"source": P("a"), "series": "s", "tags": {"x": "y"}, "mode": "gauge"},
        )
        await c.i_sync()
        await sf.run("link metrics srv1 delete")
        await c.i_sync()
        with pytest.raises(KeyError):
            await c.d_get(prefix + P("srv1"))
        with pytest.raises(KeyError):
            await c.d_get(prefix + P("srv1.child"))


async def test_at_lifecycle(cfg):
    """Add, modify and delete a series entry via the CLI."""

    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as c,
    ):
        prefix = cfg.link.metrics.prefix

        await sf.run("link metrics srv1 add -b akumuli -h h -p 1")
        await c.d_set(P("src.value"), 42)
        await c.i_sync()

        await sf.run(
            "link metrics srv1 at entry1 add src.value series1 host=h1 kind=temp",
        )
        await c.i_sync()

        ev = await c.d_get(prefix + P("srv1.entry1"))
        assert ev["source"] == P("src.value")
        assert ev["series"] == "series1"
        assert ev["tags"] == {"host": "h1", "kind": "temp"}
        assert ev["mode"] == "gauge"

        # adding again without --force fails
        import asyncclick as click  # noqa:PLC0415

        with _raises(click.UsageError) as r:
            await sf.run(
                "link metrics srv1 at entry1 add src.value series1 host=h1",
            )
        assert r.value is not None
        assert "already exists" in r.value.format_message().lower()

        # at PATH delete: non-recursive leaves children alone
        await c.d_set(
            prefix + P("srv1.entry1.sub"),
            {"source": P("src.value"), "series": "s", "tags": {"a": "b"}, "mode": "gauge"},
        )
        await c.i_sync()
        await sf.run("link metrics srv1 at entry1 delete")
        await c.i_sync()
        with pytest.raises(KeyError):
            await c.d_get(prefix + P("srv1.entry1"))
        child = await c.d_get(prefix + P("srv1.entry1.sub"))
        assert child["series"] == "s"

        # at PATH delete -r removes the subtree
        await sf.run("link metrics srv1 at entry1 delete -r")
        await c.i_sync()
        with pytest.raises(KeyError):
            await c.d_get(prefix + P("srv1.entry1.sub"))
