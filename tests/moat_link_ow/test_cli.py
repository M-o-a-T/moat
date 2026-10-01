"""End-to-end tests for ``moat.link.ow`` CLI commands.

Run through :py:meth:`moat.link._test.Scaffold.run` so the entire
``asyncclick`` decorator stack is exercised.
"""

from __future__ import annotations

import pytest

import asyncclick as click

import moat.link.ow  # noqa:F401 - register cfg
from moat.util import yload
from moat.lib.path import P, Path
from moat.link._test import Scaffold
from moat.src.test import raises as _raises

pytestmark = pytest.mark.anyio

FAM = 0x10
CODE = 0x0BAC6B010800
DEV = "10.0bac6b010800"


def _dev(prefix, *attr) -> Path:
    "The path of the test device, or an attribute mapping below it."
    return (
        prefix + Path.build((FAM, CODE)) + P(".".join(attr))
        if attr
        else prefix + Path.build((FAM, CODE))
    )


async def test_server(cfg):
    """Add, set, show, list and delete an owserver."""
    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as c,
    ):
        prefix = cfg.link.ow.prefix
        spath = prefix + P("server.g1")

        await sf.run("link ow server g1 add -h 10.0.0.1 -p 4305")
        await c.i_sync()
        assert await c.d_get(spath) == {"server": {"host": "10.0.0.1", "port": 4305}}

        with _raises(click.UsageError) as r:
            await sf.run("link ow server g1 add -h other")
        assert "already exists" in r.value.format_message().lower()

        with _raises(click.UsageError) as r:
            await sf.run("link ow server g2 add -p 1")
        assert "host" in r.value.format_message().lower()

        await sf.run("link ow server g1 set -h 10.0.0.2")
        await c.i_sync()
        assert await c.d_get(spath) == {"server": {"host": "10.0.0.2", "port": 4305}}

        r = await sf.run("link ow server g1")
        assert yload(r.stdout) == {"server": {"host": "10.0.0.2", "port": 4305}}

        r = await sf.run("link ow server -")
        assert r.stdout.split() == ["g1"]

        await sf.run("link ow server g1 delete")
        await c.i_sync()
        with pytest.raises(KeyError):
            await c.d_get(spath)


async def test_at(cfg):
    """Families, devices and attribute mappings."""
    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as c,
    ):
        prefix = cfg.link.ow.prefix

        # a read mapping
        await sf.run(f"link ow at {DEV}.temperature add -s dest .data.temp -i 5")
        await c.i_sync()
        assert await c.d_get(_dev(prefix, "temperature")) == {
            "dest": P("data.temp"),
            "interval": 5,
        }

        with _raises(click.UsageError) as r:
            await sf.run(f"link ow at {DEV}.temperature add -s dest .data.temp")
        assert "already exists" in r.value.format_message().lower()

        # missing dest/src: nothing is written
        with _raises(click.UsageError) as r:
            await sf.run(f"link ow at {DEV}.humidity add -i 5")
        assert "dest" in r.value.format_message().lower()
        with _raises(click.UsageError) as r:
            await sf.run(f"link ow at {DEV}.foo add -w -a bar:1")
        assert "src" in r.value.format_message().lower()
        await c.i_sync()
        with pytest.raises(KeyError):
            await c.d_get(_dev(prefix, "humidity"))

        # adding needs an attribute
        with _raises(click.UsageError) as r:
            await sf.run(f"link ow at {DEV} add -s dest .x")
        assert "attr" in r.value.format_message().lower()

        # a write mapping, nested
        await sf.run(f"link ow at {DEV}.foo.bar add -w -s src .data.low -a bar:1")
        await c.i_sync()
        assert await c.d_get(_dev(prefix, "foo.bar")) == {
            "src": P("data.low"),
            "src_attr": P("bar:1"),
        }

        # device settings
        await sf.run(f"link ow at {DEV} set -s interval =30")
        await c.i_sync()
        assert await c.d_get(_dev(prefix)) == {"interval": 30}

        # family settings
        await sf.run("link ow at 10 set -s interval =60 -s idem =False")
        await c.i_sync()
        assert await c.d_get(prefix + Path.build((FAM,))) == {"interval": 60, "idem": False}

        r = await sf.run("link ow at 10 get")
        assert yload(r.stdout) == {"interval": 60, "idem": False}
        r = await sf.run("link ow at 10 get interval")
        assert yload(r.stdout) == 60
        r = await sf.run("link ow at 10 get interval idem")
        assert yload(r.stdout) == {"interval": 60, "idem": False}

        r = await sf.run(f"link ow at {DEV}.temperature get dest")
        assert yload(r.stdout) == P("data.temp")
        r = await sf.run(f"link ow at {DEV}.temperature")
        assert yload(r.stdout)["interval"] == 5

        # listings show hex codes
        await sf.run("link ow at 05.345678.x add -s dest .y")
        await c.i_sync()
        r = await sf.run("link ow at -")
        assert r.stdout.split() == ["05", "10"]
        r = await sf.run("link ow at 10")
        assert r.stdout.split() == [DEV]
        r = await sf.run(f"link ow at {DEV}")
        assert sorted(r.stdout.split()) == [f"{DEV}.foo.bar", f"{DEV}.temperature"]

        r = await sf.run("link ow dump")
        d = yload(r.stdout)
        assert d["10"]["0bac6b010800"]["temperature"]["_"]["interval"] == 5
        assert d["05"]["000000345678"]["x"]["_"]["dest"] == P("y")

        with _raises(click.UsageError) as r:
            await sf.run("link ow at 1x")
        assert "family" in r.value.format_message().lower()

        # delete
        await sf.run(f"link ow at {DEV}.temperature delete")
        await c.i_sync()
        with pytest.raises(KeyError):
            await c.d_get(_dev(prefix, "temperature"))
        with _raises(click.UsageError):
            await sf.run(f"link ow at {DEV}.temperature delete")
