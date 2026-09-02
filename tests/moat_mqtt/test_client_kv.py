# Copyright (c) 2015 Nicolas JOUANIN  # noqa: D100
#
# See the file license.txt for copying permission.
from __future__ import annotations

import anyio
import logging
import pytest

try:
    from contextlib import asynccontextmanager
except ImportError:
    from async_generator import asynccontextmanager

from moat.util import gen_ident
from moat.mqtt.broker import create_broker
from moat.mqtt.client import open_mqttclient
from moat.mqtt.mqtt.constants import QOS_0

try:
    from moat.kv.client import open_client
    from moat.kv.server import Server
except ImportError:
    pytestmark = pytest.mark.skip

from functools import partial

from . import anyio_run

log = logging.getLogger(__name__)


def _configs():
    """Build configs for the base broker, kv server, and moat-kv broker.

    All listeners bind to port 0 (OS-assigned). The real ports are filled
    in by :func:`moat_kv_server` after the base broker and kv server start.
    """
    broker_config = {
        "broker": {"uri": None},  # filled in after base broker starts
        "kv": {
            "topic": "test_" + gen_ident(7, alphabet="al_az"),
            "base": ("test", "retain"),
            "transparent": (("test", "vis"),),
            "conn": {"port": None},  # filled in after kv server starts
            "server": {
                "backend": "mqtt",
                "mqtt": {"uri": None},  # filled in after base broker starts
                "bind": [{"host": "localhost", "port": 0, "ssl": False}],
            },
        },
        "listeners": {"default": {"type": "tcp", "bind": "127.0.0.1:0", "max_connections": 10}},
        "sys_interval": 0,
        "auth": {"allow-anonymous": True},
    }

    test_config = {
        "listeners": {
            "default": {"type": "tcp", "bind": "127.0.0.1:0", "max_connections": 10},
        },
        "sys_interval": 0,
        "retain": False,
        "auth": {"allow-anonymous": True},
    }
    return broker_config, test_config


@asynccontextmanager
async def moat_kv_server(n, broker_config, test_config):  # noqa: D103
    msgs = []
    async with (
        anyio.create_task_group() as tg,
        create_broker(test_config, plugin_namespace="moat.mqtt.test.plugins") as base_broker,
    ):
        # Read back the base broker's OS-assigned port and fill in the URIs.
        port_b = base_broker._servers["default"].port  # noqa: SLF001
        uri_b = f"mqtt://127.0.0.1:{port_b}"
        broker_config["broker"]["uri"] = uri_b
        broker_config["kv"]["server"]["mqtt"]["uri"] = uri_b

        s = Server("test", cfg=broker_config["kv"], init="test")
        evt = anyio.Event()
        tg.start_soon(partial(s.serve, ready_evt=evt))
        await evt.wait()

        # Read back the kv server's OS-assigned port and fill in the client config.
        port_d = s.ports[0][1]
        broker_config["kv"]["conn"]["port"] = port_d

        async with open_client(**broker_config["kv"]) as cl:

            async def msglog(evt):
                try:
                    async with cl._stream(  # noqa: SLF001
                        "msg_monitor",
                        topic="*",
                    ) as mon:  # , topic=broker_config['kv']['topic']) as mon:
                        log.info("Monitor Start")
                        evt.set()
                        async for m in mon:
                            log.info("Monitor Msg %r", m.data)
                            msgs.append(m.data)
                except Exception:
                    log.exception("DEAD")

            evt = anyio.Event()
            await cl.scope.spawn(msglog, evt)
            await evt.wait()
            yield s
            cl.scope.cancel()
        tg.cancel_scope.cancel()
    if len(msgs) != n:
        log.error("MsgCount %d %d", len(msgs), n)
    # assert len(msgs) == n, msgs


class TestMQTTClient:  # noqa:D101
    def test_deliver(self, cfg):  # noqa: D102
        cfg  # noqa:B018
        data = b"data 123 a"

        async def test_coro():
            broker_config, test_config = _configs()
            async with moat_kv_server(1, broker_config, test_config):
                async with create_broker(broker_config, plugin_namespace="moat.mqtt.test.plugins"):
                    async with open_mqttclient(config=broker_config["broker"]) as client:
                        assert client.session is not None
                        ret = await client.subscribe([("test_topic", QOS_0)])
                        assert ret[0] == QOS_0
                        async with open_mqttclient(config=broker_config["broker"]) as client_pub:
                            await client_pub.publish("test_topic", data, QOS_0, retain=False)
                        with anyio.fail_after(0.5):
                            message = await client.deliver_message()
                        assert message is not None
                        assert message.publish_packet is not None
                        assert message.data == data
                        pass  # exit client
                    pass  # exit broker
                pass  # exit server
            pass  # exit test

        anyio_run(test_coro, backend="trio")

    def test_deliver_transparent(self, cfg):  # noqa: D102
        cfg  # noqa:B018
        data = b"data 123 t"

        async def test_coro():
            broker_config, test_config = _configs()
            async with moat_kv_server(1, broker_config, test_config):
                async with create_broker(broker_config, plugin_namespace="moat.mqtt.test.plugins"):
                    async with open_mqttclient(config=broker_config["broker"]) as client:
                        assert client.session is not None
                        ret = await client.subscribe([("test/vis/foo", QOS_0)])
                        assert ret[0] == QOS_0
                        async with open_mqttclient(config=broker_config["broker"]) as client_pub:
                            await client_pub.publish("test/vis/foo", data, QOS_0, retain=False)
                        with anyio.fail_after(0.5):
                            message = await client.deliver_message()
                        assert message is not None
                        assert message.publish_packet is not None
                        assert message.data == data
                        pass  # exit client
                    pass  # exit broker
                pass  # exit server
            pass  # exit test

        anyio_run(test_coro, backend="trio")

    def test_deliver_direct(self, cfg):  # noqa: D102
        cfg  # noqa:B018
        data = b"data 123 b"

        async def test_coro():
            broker_config, test_config = _configs()
            async with (
                moat_kv_server(0, broker_config, test_config),
                create_broker(broker_config, plugin_namespace="moat.mqtt.test.plugins"),
                open_mqttclient(config=broker_config["broker"]) as client,
            ):
                assert client.session is not None
                ret = await client.subscribe([("test_topic", QOS_0)])
                assert ret[0] == QOS_0
                async with open_mqttclient(config=broker_config["broker"]) as client_pub:
                    await client_pub.publish("test_topic", data, QOS_0, retain=False)
                with anyio.fail_after(0.5):
                    message = await client.deliver_message()
                assert message is not None
                assert message.publish_packet is not None
                assert message.data == data

        anyio_run(test_coro, backend="trio")

    def test_deliver_timeout(self, cfg):  # noqa: D102
        cfg  # noqa:B018

        async def test_coro():
            broker_config, test_config = _configs()
            async with (
                moat_kv_server(0, broker_config, test_config),
                create_broker(broker_config, plugin_namespace="moat.mqtt.test.plugins"),
                open_mqttclient(config=broker_config["broker"]) as client,
            ):
                assert client.session is not None
                ret = await client.subscribe([("test_topic", QOS_0)])
                assert ret[0] == QOS_0
                with (
                    pytest.raises(TimeoutError),
                    anyio.fail_after(2),
                ):
                    await client.deliver_message()

        anyio_run(test_coro, backend="trio")
