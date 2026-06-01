"""End-to-end tests for ``moat.link.knx`` CLI commands.

Run through :py:meth:`moat.link._test.Scaffold.run` so the entire
``asyncclick`` decorator stack is exercised.
"""

from __future__ import annotations

import pytest

import asyncclick as click

import moat.link.knx  # noqa:F401 - register cfg
from moat.lib.path import P
from moat.link._test import Scaffold
from moat.src.test import raises as _raises

pytestmark = pytest.mark.anyio


async def test_server_lifecycle(cfg):
    """Add, set, list and delete a KNX gateway via the CLI."""

    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as c,
    ):
        prefix = cfg.link.knx.prefix

        await sf.run("link knx g1 add -h 10.0.0.1 -p 3671")
        await c.i_sync()

        data = await c.d_get(prefix + P("g1"))
        assert data == {"server": {"host": "10.0.0.1", "port": 3671}}

        # second add without --force fails
        with _raises(click.UsageError) as r:
            await sf.run("link knx g1 add -h other -p 1")
        assert r.value is not None
        assert "already exists" in r.value.format_message().lower()

        # set updates fields
        await sf.run("link knx g1 set -h 10.0.0.2")
        await c.i_sync()
        data = await c.d_get(prefix + P("g1"))
        assert data["server"]["host"] == "10.0.0.2"
        assert data["server"]["port"] == 3671

        # list servers
        r = await sf.run("link knx -")
        assert "g1" in r.stdout

        # delete
        await sf.run("link knx g1 delete")
        await c.i_sync()
        with pytest.raises(KeyError):
            await c.d_get(prefix + P("g1"))


async def test_at_addr_lifecycle(cfg):
    """``at a/b/c`` translates the group address into a 3-element subpath.

    Exercise the same workflow that ``./mt kv knx addr test 1/2/3 -m Bool
    -t in -a dest data.foo.bar`` performs.
    """

    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as c,
    ):
        prefix = cfg.link.knx.prefix

        await sf.run("link knx g1 add -h 10.0.0.1 -p 3671")
        await c.d_set(P("src.value"), 42)
        await c.i_sync()

        # mimic `add -t in -m Bool -s dest .data.foo.bar`
        await sf.run("link knx g1 at 1/2/3 add -t in -m Bool -s dest .data.foo.bar")
        await c.i_sync()

        stored = await c.d_get(prefix + P("g1") + P(":1:2:3"))
        assert stored["type"] == "in"
        assert stored["mode"] == "Bool"
        assert stored["dest"] == P("data.foo.bar")

        # adding again without --force is an error
        with _raises(click.UsageError) as r:
            await sf.run("link knx g1 at 1/2/3 add -t in -m Bool -s dest .data.foo.bar")
        assert r.value is not None
        assert "already exists" in r.value.format_message().lower()

        # type=in without dest fails the post-add validation
        with _raises(click.UsageError) as r:
            await sf.run("link knx g1 at 4/5/6 add -t in -m Bool")
        assert r.value is not None
        assert "dest" in r.value.format_message().lower()

        # delete
        await sf.run("link knx g1 at 1/2/3 delete")
        await c.i_sync()
        with pytest.raises(KeyError):
            await c.d_get(prefix + P("g1") + P(":1:2:3"))
