"""End-to-end tests for ``moat.link.metrics`` CLI commands."""

from __future__ import annotations

import pytest
from io import StringIO

import asyncclick as click

from moat.util import attrdict
from moat.lib.path import P
from moat.link._test import Scaffold
from moat.link.metrics import _main as cmd

pytestmark = pytest.mark.anyio


def _wrapped(c):
    """Strip click decorators to call a command callback directly."""
    return c.callback.__wrapped__


async def _obj(cfg, c):
    """Build the ``obj`` attrdict the CLI callbacks expect."""
    return attrdict(
        cfg=cfg,
        conn=c,
        debug=False,
        stdout=StringIO(),
        metrics_cfg=cfg.link.metrics,
        metrics_prefix=cfg.link.metrics.prefix,
    )


async def test_server_lifecycle(cfg):
    """Add, set, list and delete a server."""

    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as c,
    ):
        prefix = cfg.link.metrics.prefix
        obj = await _obj(cfg, c)
        obj.metrics_name = "srv1"

        await _wrapped(cmd.add)(
            obj,
            backend="akumuli",
            host="example.com",
            port=8282,
            topic=None,
            force=False,
        )
        await c.i_sync()

        data = await c.d_get(prefix + P("srv1"))
        assert data == {"server": {"backend": "akumuli", "host": "example.com", "port": 8282}}

        # second add without --force fails
        with pytest.raises(click.UsageError):
            await _wrapped(cmd.add)(
                obj,
                backend="akumuli",
                host="other",
                port=8000,
                topic=None,
                force=False,
            )

        # set updates fields
        await _wrapped(cmd.set_)(
            obj,
            backend=None,
            host="newhost",
            port=None,
            topic=P("raw.topic"),
        )
        await c.i_sync()
        data = await c.d_get(prefix + P("srv1"))
        assert data["server"]["host"] == "newhost"
        assert data["server"]["port"] == 8282
        assert data["server"]["backend"] == "akumuli"
        assert data["topic"] == P("raw.topic")

        # listing
        seen = []
        async with c.d_walk(prefix, min_depth=1, max_depth=1) as mon:
            async for p, _d in mon:
                seen.append(p[-1])
        assert seen == ["srv1"]

        # delete
        obj.metrics_name = "srv1"
        await _wrapped(cmd.delete_)(obj, recursive=False)
        await c.i_sync()
        with pytest.raises(KeyError):
            await c.d_get(prefix + P("srv1"))


async def test_at_lifecycle(cfg):
    """Add, modify and delete a series entry under a server."""

    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as c,
    ):
        prefix = cfg.link.metrics.prefix
        obj = await _obj(cfg, c)
        obj.metrics_name = "srv1"

        await _wrapped(cmd.add)(
            obj,
            backend="akumuli",
            host="h",
            port=1,
            topic=None,
            force=False,
        )
        await c.d_set(P("src.value"), 42)
        await c.i_sync()

        # at_cli is a group; invoke its callback to set up subpath
        obj.metrics_subpath = P("entry1")

        await _wrapped(cmd.add_at)(
            obj,
            source=P("src.value"),
            mode="gauge",
            attr=None,
            series="series1",
            tags=("host=h1", "kind=temp"),
            force=False,
        )
        await c.i_sync()

        ev = await c.d_get(prefix + P("srv1.entry1"))
        assert ev["source"] == P("src.value")
        assert ev["series"] == "series1"
        assert ev["tags"] == {"host": "h1", "kind": "temp"}
        assert ev["mode"] == "gauge"

        # adding again without --force fails
        with pytest.raises(click.UsageError):
            await _wrapped(cmd.add_at)(
                obj,
                source=P("src.value"),
                mode="gauge",
                attr=None,
                series="series1",
                tags=("host=h1",),
                force=False,
            )

        # at PATH delete
        await _wrapped(cmd.delete_at)(obj)
        await c.i_sync()
        with pytest.raises(KeyError):
            await c.d_get(prefix + P("srv1.entry1"))
