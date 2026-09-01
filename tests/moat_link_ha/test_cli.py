"""End-to-end tests for ``moat.link.ha`` CLI commands.

Run through :py:meth:`moat.link._test.Scaffold.run` so the entire
``asyncclick`` decorator stack is exercised.
"""

from __future__ import annotations

import pytest

import moat.link.ha  # noqa:F401 - register cfg
from moat.lib.path import P
from moat.link._test import Scaffold

pytestmark = pytest.mark.anyio


async def test_device_lifecycle(cfg):
    """Add, get, and delete a HA device via the CLI."""

    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as c,
    ):
        # add a light device
        await sf.run("link ha set light kitchen -s uid my-light-1")
        await c.i_sync()

        # verify it was stored
        ha_prefix = cfg.link.ha.prefix
        data = await c.d_get(ha_prefix + P("light.kitchen.config"))
        assert data["unique_id"] == "my-light-1"
        assert "state_topic" in data
        assert "command_topic" in data

        # get the device back
        r = await sf.run("link ha get light kitchen")
        assert "my-light-1" in r.stdout

        # delete
        await sf.run("link ha delete light kitchen")
        await c.i_sync()
        with pytest.raises(KeyError):
            await c.d_get(ha_prefix + P("light.kitchen.config"))


async def test_list_types(cfg):
    """Listing device types works."""

    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
    ):
        r = await sf.run("link ha set - - -L")
        assert "light" in r.stdout
        assert "switch" in r.stdout
        assert "sensor" in r.stdout
