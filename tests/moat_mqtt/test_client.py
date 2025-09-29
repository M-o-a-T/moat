# Copyright (c) 2015 Nicolas JOUANIN  # noqa: D100
#
# See the file license.txt for copying permission.
from __future__ import annotations

import anyio
import logging
import os
import pytest
import unittest
from anyio.pytest_plugin import FreePortFactory
from socket import SOCK_STREAM

from moat.util import ungroup
from moat.mqtt.broker import create_broker
from moat.mqtt.client import ConnectException, open_mqttclient
from moat.mqtt.mqtt.constants import QOS_0, QOS_1, QOS_2

from . import anyio_run

log = logging.getLogger(__name__)


def _PUB():
    pf = FreePortFactory(SOCK_STREAM)
    PORT = pf()
    WSPORT = pf()
    WSSPORT = pf()
    URI = f"mqtt://127.0.0.1:{PORT}/"

    broker_config = {
        "listeners": {
            "mqtt": {"type": "tcp", "bind": f"127.0.0.1:{PORT}", "max_connections": 10},
            "ws": {"type": "ws", "bind": f"127.0.0.1:{WSPORT}", "max_connections": 10},
            "wss": {"type": "ws", "bind": f"127.0.0.1:{WSSPORT}", "max_connections": 10},
        },
        "sys_interval": 0,
        "auth": {"allow-anonymous": True},
    }
    return PORT, WSPORT, WSSPORT, URI, broker_config


class MQTTClientTest(unittest.TestCase):  # noqa: D101
    @pytest.mark.skip
    def test_connect_tcp(self):  # noqa: D102
        async def test_coro():
            async with open_mqttclient() as client:
                await client.connect("mqtt://test.mosquitto.org/")
                assert client.session is not None

        try:
            anyio_run(test_coro)
        except ConnectException:
            log.error("Broken by server")

    @pytest.mark.skip
    def test_connect_tcp_secure(self):  # noqa: D102
        async def test_coro():
            async with open_mqttclient(config={"check_hostname": False}) as client:
                ca = os.path.join(os.path.dirname(os.path.realpath(__file__)), "mosquitto.org.crt")
                await client.connect("mqtts://test.mosquitto.org/", cafile=ca)
                assert client.session is not None

        try:
            with ungroup:
                anyio_run(test_coro)
        except ConnectException:
            log.error("Broken by server")

    def test_connect_tcp_failure(self):  # noqa: D102
        async def test_coro():
            _, _, _, URI, _broker_config = _PUB()
            with pytest.raises(ConnectException), ungroup:
                config = {"auto_reconnect": False}
                async with open_mqttclient(config=config) as client:
                    await client.connect(URI)

        anyio_run(test_coro)

    @pytest.mark.skip
    def test_uri_supplied_early(self):  # noqa: D102
        config = {"auto_reconnect": False}

        async def test_coro():
            async with open_mqttclient("mqtt://test.mosquitto.org/", config=config) as client:
                assert client.session is not None

        try:
            anyio_run(test_coro)
        except ConnectException:
            log.error("Broken by server")

    def test_connect_ws(self):  # noqa: D102
        async def test_coro():
            _, WSPORT, _, _, broker_config = _PUB()
            async with (
                create_broker(broker_config, plugin_namespace="moat.mqtt.test.plugins"),
                open_mqttclient() as client,
            ):
                await client.connect(f"ws://127.0.0.1:{WSPORT}/")
                assert client.session is not None

        anyio_run(test_coro, backend="trio")

    def test_reconnect_ws_retain_username_password(self):  # noqa: D102
        async def test_coro():
            _, WSPORT, _, _, broker_config = _PUB()
            async with (
                create_broker(broker_config, plugin_namespace="moat.mqtt.test.plugins"),
                open_mqttclient() as client,
            ):
                await client.connect(f"ws://fred:password@127.0.0.1:{WSPORT}/")
                assert client.session is not None
                await client.reconnect()

                assert client.session.username is not None
                assert client.session.password is not None

        anyio_run(test_coro, backend="trio")

    def test_connect_ws_secure(self):  # noqa: D102
        async def test_coro():
            _, _, WSSPORT, _, broker_config = _PUB()
            async with (
                create_broker(broker_config, plugin_namespace="moat.mqtt.test.plugins"),
                open_mqttclient() as client,
            ):
                ca = os.path.join(
                    os.path.dirname(os.path.realpath(__file__)),
                    "mosquitto.org.crt",
                )
                await client.connect(f"ws://127.0.0.1:{WSSPORT}/", cafile=ca)
                assert client.session is not None

        anyio_run(test_coro, backend="trio")

    def test_ping(self):  # noqa: D102
        async def test_coro():
            _, _, _, URI, broker_config = _PUB()
            async with (
                create_broker(broker_config, plugin_namespace="moat.mqtt.test.plugins"),
                open_mqttclient() as client,
            ):
                await client.connect(URI)
                assert client.session is not None
                await client.ping()

        anyio_run(test_coro, backend="trio")

    def test_subscribe(self):  # noqa: D102
        async def test_coro():
            _, _, _, URI, broker_config = _PUB()
            async with (
                create_broker(broker_config, plugin_namespace="moat.mqtt.test.plugins"),
                open_mqttclient() as client,
            ):
                await client.connect(URI)
                assert client.session is not None
                ret = await client.subscribe(
                    [
                        ("$SYS/broker/uptime", QOS_0),
                        ("$SYS/broker/uptime", QOS_1),
                        ("$SYS/broker/uptime", QOS_2),
                    ],
                )
                assert ret[0] == QOS_0
                assert ret[1] == QOS_1
                assert ret[2] == QOS_2

        anyio_run(test_coro, backend="trio")

    def test_unsubscribe(self):  # noqa: D102
        async def test_coro():
            _, _, _, URI, broker_config = _PUB()
            async with (
                create_broker(broker_config, plugin_namespace="moat.mqtt.test.plugins"),
                open_mqttclient() as client,
            ):
                await client.connect(URI)
                assert client.session is not None
                ret = await client.subscribe([("$SYS/broker/uptime", QOS_0)])
                assert ret[0] == QOS_0
                await client.unsubscribe(["$SYS/broker/uptime"])

        anyio_run(test_coro, backend="trio")

    def test_deliver(self):  # noqa: D102
        data = b"data"

        async def test_coro():
            _, _, _, URI, broker_config = _PUB()
            async with (
                create_broker(broker_config, plugin_namespace="moat.mqtt.test.plugins"),
                open_mqttclient() as client,
            ):
                await client.connect(URI)
                assert client.session is not None
                ret = await client.subscribe([("test_topic", QOS_0)])
                assert ret[0] == QOS_0
                async with open_mqttclient() as client_pub:
                    await client_pub.connect(URI)
                    await client_pub.publish("test_topic", data, QOS_0)
                message = await client.deliver_message()
                assert message is not None
                assert message.publish_packet is not None
                assert message.data == data
                await client.unsubscribe(["$SYS/broker/uptime"])

        anyio_run(test_coro, backend="trio")

    def test_deliver_timeout(self):  # noqa: D102
        async def test_coro():
            _, _, _, URI, broker_config = _PUB()
            async with (
                create_broker(broker_config, plugin_namespace="moat.mqtt.test.plugins"),
                open_mqttclient() as client,
            ):
                await client.connect(URI)
                assert client.session is not None
                ret = await client.subscribe([("test_topic", QOS_0)])
                assert ret[0] == QOS_0
                with pytest.raises(TimeoutError), anyio.fail_after(2):
                    await client.deliver_message()
                await client.unsubscribe(["$SYS/broker/uptime"])

        anyio_run(test_coro, backend="trio")
