"""End-to-end tests for ``moat.link.knx`` CLI commands."""

from __future__ import annotations

import pytest
from io import StringIO

import asyncclick as click

from moat.util import attrdict
from moat.lib.path import P
from moat.link._test import Scaffold
from moat.link.knx import _main as cmd

pytestmark = pytest.mark.anyio


def _wrapped(c):
    """Strip click decorators to call a command callback directly."""
    return c.callback.__wrapped__


def _obj(cfg, c):
    """Build the ``obj`` attrdict the CLI callbacks expect."""
    return attrdict(
        cfg=cfg,
        conn=c,
        debug=False,
        stdout=StringIO(),
        knx_cfg=cfg.link.knx,
        knx_prefix=cfg.link.knx.prefix,
    )


async def test_server_lifecycle(cfg):
    """Add, set, list and delete a KNX gateway."""

    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as c,
    ):
        prefix = cfg.link.knx.prefix
        obj = _obj(cfg, c)
        obj.knx_name = "g1"

        await _wrapped(cmd.add)(obj, host="10.0.0.1", port=3671, force=False)
        await c.i_sync()

        data = await c.d_get(prefix + P("g1"))
        assert data == {"server": {"host": "10.0.0.1", "port": 3671}}

        # second add without --force fails
        with pytest.raises(click.UsageError):
            await _wrapped(cmd.add)(obj, host="x", port=1, force=False)

        # set updates fields
        await _wrapped(cmd.set_)(obj, host="10.0.0.2", port=None)
        await c.i_sync()
        data = await c.d_get(prefix + P("g1"))
        assert data["server"]["host"] == "10.0.0.2"
        assert data["server"]["port"] == 3671

        # delete
        await _wrapped(cmd.delete_)(obj, recursive=False)
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
        obj = _obj(cfg, c)
        obj.knx_name = "g1"

        await _wrapped(cmd.add)(obj, host="10.0.0.1", port=3671, force=False)
        await c.i_sync()

        # The CLI `at 1/2/3` would parse to (1,2,3); we set it directly here.
        from moat.link.knx.model import group_subpath  # noqa: PLC0415

        obj.knx_subpath = group_subpath("1/2/3")

        # mimic `add -t in -m Bool -s dest .data.foo.bar`
        await _wrapped(cmd.add_at)(
            obj,
            typ="in",
            mode="Bool",
            force=False,
            set_=(("dest", ".data.foo.bar"),),
            args_=(),
            vars_=(),
            eval_=(),
            path_=(),
            proxy_=(),
        )
        await c.i_sync()

        stored = await c.d_get(prefix + P("g1") + P(":1:2:3"))
        assert stored["type"] == "in"
        assert stored["mode"] == "Bool"
        assert stored["dest"] == P("data.foo.bar")

        # Adding the same address without --force is an error
        with pytest.raises(click.UsageError):
            await _wrapped(cmd.add_at)(
                obj,
                typ="in",
                mode="Bool",
                force=False,
                set_=(("dest", ".data.foo.bar"),),
                args_=(),
                vars_=(),
                eval_=(),
                path_=(),
                proxy_=(),
            )

        # type=in without dest fails the post-add validation
        obj.knx_subpath = group_subpath("4/5/6")
        with pytest.raises(click.UsageError):
            await _wrapped(cmd.add_at)(
                obj,
                typ="in",
                mode="Bool",
                force=False,
                set_=(),
                args_=(),
                vars_=(),
                eval_=(),
                path_=(),
                proxy_=(),
            )

        # delete the first one
        obj.knx_subpath = group_subpath("1/2/3")
        await _wrapped(cmd.delete_at)(obj)
        await c.i_sync()
        with pytest.raises(KeyError):
            await c.d_get(prefix + P("g1") + P(":1:2:3"))
