"""End-to-end tests for ``moat.link.gpio`` CLI commands.

Run through :py:meth:`moat.link._test.Scaffold.run` so the entire
``asyncclick`` decorator stack is exercised.
"""

from __future__ import annotations

import pytest

import moat.link.gpio  # noqa:F401 - register cfg
from moat.lib.path import P
from moat.link._test import Scaffold

pytestmark = pytest.mark.anyio


async def test_port_lifecycle(cfg):
    """Add and delete a GPIO port via the CLI."""

    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as c,
    ):
        prefix = cfg.link.gpio.prefix

        # add an input port
        await sf.run("link gpio port myhost.chip0:5 -t input -m read -a dest sensors.btn")
        await c.i_sync()

        data = await c.d_get(prefix + P("myhost.chip0:5"))
        assert data["type"] == "input"
        assert data["mode"] == "read"
        assert data["dest"] == P("sensors.btn")

        # delete
        await sf.run("link gpio delete myhost.chip0:5")
        await c.i_sync()
        with pytest.raises(KeyError):
            await c.d_get(prefix + P("myhost.chip0:5"))


async def test_port_output(cfg):
    """Add an output port."""

    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as c,
    ):
        prefix = cfg.link.gpio.prefix

        await sf.run("link gpio port myhost.chip0:3 -t output -m write -a src controls.lamp")
        await c.i_sync()

        data = await c.d_get(prefix + P("myhost.chip0:3"))
        assert data["type"] == "output"
        assert data["mode"] == "write"
        assert data["src"] == P("controls.lamp")


async def test_attr_modify(cfg):
    """Modify attributes via the attr command."""

    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as c,
    ):
        prefix = cfg.link.gpio.prefix

        # add a port first
        await sf.run("link gpio port myhost.chip0:7 -t input -m read -a dest sensors.btn")
        await c.i_sync()

        # modify an attribute — use eval syntax (=True) since attr uses process_args
        await sf.run("link gpio attr myhost.chip0:7 -s low =True")
        await c.i_sync()

        data = await c.d_get(prefix + P("myhost.chip0:7"))
        assert data["low"] is True
