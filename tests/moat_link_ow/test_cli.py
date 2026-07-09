"""End-to-end tests for ``moat.link.ow`` CLI commands.

Run through :py:meth:`moat.link._test.Scaffold.run` so the entire
``asyncclick`` decorator stack is exercised.
"""

from __future__ import annotations

import pytest

import asyncclick as click

import moat.link.ow  # noqa:F401 - register cfg
from moat.lib.path import P
from moat.link._test import Scaffold
from moat.link.ow.model import device_subpath
from moat.src.test import raises as _raises

pytestmark = pytest.mark.anyio


def _entry(prefix, server: str, device: str, attr: str):
    """Build the link path of one attribute mapping."""
    return prefix + P(server) + device_subpath(device) + P(attr)


async def test_server_lifecycle(cfg):
    """Add, set, list and delete an OWFS server via the CLI."""

    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as c,
    ):
        prefix = cfg.link.ow.prefix

        await sf.run("link ow g1 add -h 10.0.0.1 -p 4304")
        await c.i_sync()

        data = await c.d_get(prefix + P("g1"))
        assert data == {"server": {"host": "10.0.0.1", "port": 4304}}

        # second add without --force fails
        with _raises(click.UsageError) as r:
            await sf.run("link ow g1 add -h other -p 1")
        assert r.value is not None
        assert "already exists" in r.value.format_message().lower()

        # set updates fields
        await sf.run("link ow g1 set -h 10.0.0.2")
        await c.i_sync()
        data = await c.d_get(prefix + P("g1"))
        assert data["server"]["host"] == "10.0.0.2"
        assert data["server"]["port"] == 4304

        # list servers
        r = await sf.run("link ow -")
        assert "g1" in r.stdout

        # delete
        await sf.run("link ow g1 delete")
        await c.i_sync()
        with pytest.raises(KeyError):
            await c.d_get(prefix + P("g1"))


async def test_at_attr_lifecycle(cfg):
    """``at DEVICE ATTR`` manages a single attribute mapping."""

    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as c,
    ):
        prefix = cfg.link.ow.prefix

        await sf.run("link ow g1 add -h 10.0.0.1 -p 4304")
        await c.i_sync()

        # add a read mapping
        await sf.run(
            "link ow g1 at 10.345678.90 temperature add -s dest .data.temp -s interval =5"
        )
        await c.i_sync()

        stored = await c.d_get(_entry(prefix, "g1", "10.345678.90", "temperature"))
        assert stored["dest"] == P("data.temp")
        assert stored["interval"] == 5

        # adding again without --force is an error
        with _raises(click.UsageError) as r:
            await sf.run(
                "link ow g1 at 10.345678.90 temperature add -s dest .data.temp -s interval =5"
            )
        assert r.value is not None
        assert "already exists" in r.value.format_message().lower()

        # read direction without dest fails the post-add validation
        with _raises(click.UsageError) as r:
            await sf.run("link ow g1 at 10.345678.90 humidity add -s interval =5")
        assert r.value is not None
        assert "dest" in r.value.format_message().lower()

        # write direction without src fails the post-add validation
        with _raises(click.UsageError) as r:
            await sf.run("link ow g1 at 10.345678.90 foobar add -w -a bar:1")
        assert r.value is not None
        assert "src" in r.value.format_message().lower()

        # add a write mapping
        await sf.run("link ow g1 at 10.345678.90 templow add -w -s src .data.low -a bar:1")
        await c.i_sync()

        stored = await c.d_get(_entry(prefix, "g1", "10.345678.90", "templow"))
        assert stored["src"] == P("data.low")
        assert stored["src_attr"] == P("bar:1")

        # delete
        await sf.run("link ow g1 at 10.345678.90 temperature delete")
        await c.i_sync()
        with pytest.raises(KeyError):
            await c.d_get(_entry(prefix, "g1", "10.345678.90", "temperature"))
