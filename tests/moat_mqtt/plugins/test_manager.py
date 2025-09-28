# Copyright (c) 2015 Nicolas JOUANIN  # noqa: D100
#
# See the file license.txt for copying permission.
from __future__ import annotations
import unittest

import anyio
import pytest

from moat.mqtt.plugins.manager import PluginManager

from tests.moat_mqtt import anyio_run

pytestmark = pytest.mark.skip


class SimpleTestPlugin:  # noqa: D101
    def __init__(self, context):
        self.context = context


class EventTestPlugin:  # noqa: D101
    def __init__(self, context):
        self.context = context
        self.test_flag = False
        self.coro_flag = False

    async def on_test(self, *args, **kwargs):  # pylint: disable=unused-argument  # noqa: D102
        self.test_flag = True
        self.context.logger.info("on_test")

    async def test_coro(self, *args, **kwargs):  # pylint: disable=unused-argument  # noqa: D102
        self.coro_flag = True

    async def ret_coro(self, *args, **kwargs):  # pylint: disable=unused-argument  # noqa: D102
        return "TEST"


class TestPluginManager(unittest.TestCase):  # noqa: D101
    def test_load_plugin(self):  # noqa: D102
        async def coro():
            async with anyio.create_task_group() as tg:
                manager = PluginManager(tg, "moat.mqtt.test.plugins", context=None)
                assert len(manager._plugins) > 0  # noqa: SLF001

        anyio_run(coro)

    def test_fire_event(self):  # noqa: D102
        async def fire_event(manager):
            await manager.fire_event("test")
            await anyio.sleep(1)
            await manager.close()

        async def coro():
            async with anyio.create_task_group() as tg:
                manager = PluginManager(tg, "moat.mqtt.test.plugins", context=None)
                await fire_event(manager)
                plugin = manager.get_plugin("event_plugin")
                assert plugin.object.test_flag

        anyio_run(coro)

    def test_fire_event_wait(self):  # noqa: D102
        async def fire_event(manager):
            await manager.fire_event("test", wait=True)
            await manager.close()

        async def coro():
            async with anyio.create_task_group() as tg:
                manager = PluginManager(tg, "moat.mqtt.test.plugins", context=None)
                await fire_event(manager)
                plugin = manager.get_plugin("event_plugin")
                assert plugin.object.test_flag

        anyio_run(coro)

    def test_map_coro(self):  # noqa: D102
        async def call_coro(manager):
            await manager.map_plugin_coro("test_coro")

        async def coro():
            async with anyio.create_task_group() as tg:
                manager = PluginManager(tg, "moat.mqtt.test.plugins", context=None)
                await call_coro(manager)
                plugin = manager.get_plugin("event_plugin")
                assert plugin.object.test_coro

        anyio_run(coro)

    def test_map_coro_return(self):  # noqa: D102
        async def call_coro(manager):
            return await manager.map_plugin_coro("ret_coro")

        async def coro():
            async with anyio.create_task_group() as tg:
                manager = PluginManager(tg, "moat.mqtt.test.plugins", context=None)
                ret = await call_coro(manager)
                plugin = manager.get_plugin("event_plugin")
                assert ret[plugin] == "TEST"

        anyio_run(coro)

    def test_map_coro_filter(self):
        """
        Run plugin coro but expect no return as an empty filter is given
        :return:
        """

        async def call_coro(manager):
            return await manager.map_plugin_coro("ret_coro", filter_plugins=[])

        async def coro():
            async with anyio.create_task_group() as tg:
                manager = PluginManager(tg, "moat.mqtt.test.plugins", context=None)
                ret = await call_coro(manager)
                assert len(ret) == 0

        anyio_run(coro)
