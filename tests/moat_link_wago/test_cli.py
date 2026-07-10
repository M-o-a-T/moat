"""End-to-end tests for ``moat.link.wago`` CLI commands.

Run through :py:meth:`moat.link._test.Scaffold.run` so the entire
``asyncclick`` decorator stack is exercised.
"""

from __future__ import annotations

import pytest

import asyncclick as click

import moat.link.wago  # noqa:F401 - register cfg
from moat.lib.path import P
from moat.link._test import Scaffold
from moat.src.test import raises as _raises

pytestmark = pytest.mark.anyio


async def test_server_lifecycle(cfg):
    """Add, set, list and delete a Wago controller via the CLI."""

    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as c,
    ):
        prefix = cfg.link.wago.prefix

        await sf.run("link wago c1 add -h 10.0.0.1 -p 29995")
        await c.i_sync()

        data = await c.d_get(prefix + P("c1"))
        assert data == {"server": {"host": "10.0.0.1", "port": 29995}}

        # second add without --force fails
        with _raises(click.UsageError) as r:
            await sf.run("link wago c1 add -h other -p 1")
        assert r.value is not None
        assert "already exists" in r.value.format_message().lower()

        # set updates fields
        await sf.run("link wago c1 set -h 10.0.0.2")
        await c.i_sync()
        data = await c.d_get(prefix + P("c1"))
        assert data["server"]["host"] == "10.0.0.2"
        assert data["server"]["port"] == 29995

        # list servers
        r = await sf.run("link wago -")
        assert "c1" in r.stdout

        # delete
        await sf.run("link wago c1 delete")
        await c.i_sync()
        with pytest.raises(KeyError):
            await c.d_get(prefix + P("c1"))


async def test_at_port_lifecycle(cfg):
    """``at input 1 3`` manages a single port entry."""

    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as c,
    ):
        prefix = cfg.link.wago.prefix

        await sf.run("link wago c1 add -h 10.0.0.1 -p 29995")
        await c.i_sync()

        # add a port entry
        await sf.run("link wago c1 at input 1 3 add -m read -s dest .data.foo.bar")
        await c.i_sync()

        stored = await c.d_get(prefix + P("c1") + P("input:1:3"))
        assert stored["mode"] == "read"
        assert stored["dest"] == P("data.foo.bar")

        # adding again without --force is an error
        with _raises(click.UsageError) as r:
            await sf.run("link wago c1 at input 1 3 add -m read -s dest .data.foo.bar")
        assert r.value is not None
        assert "already exists" in r.value.format_message().lower()

        # delete
        await sf.run("link wago c1 at input 1 3 delete")
        await c.i_sync()
        with pytest.raises(KeyError):
            await c.d_get(prefix + P("c1") + P("input:1:3"))
