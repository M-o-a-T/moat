# Copyright (c) 2015 Nicolas JOUANIN  # noqa: D100
#
# See the file license.txt for copying permission.
from __future__ import annotations

import anyio
import logging
import os
import pytest
import unittest

from moat.util import ungroup
from moat.mqtt.broker import create_broker
from moat.mqtt.client import ConnectException, open_mqttclient
from moat.mqtt.mqtt.constants import QOS_0, QOS_1, QOS_2

from . import anyio_run

log = logging.getLogger(__name__)


def _broker_config():
    """Build a broker config with three listeners (tcp/ws/wss) all bound to port 0.

    The real ports are read back from the broker after startup via
    ``broker._servers[<name>].port``.
    """
    broker_config = {
        "listeners": {
            "mqtt": {"type": "tcp", "bind": "127.0.0.1:0", "max_connections": 10},
            "ws": {"type": "ws", "bind": "127.0.0.1:0", "max_connections": 10},
            "wss": {"type": "ws", "bind": "127.0.0.1:0", "max_connections": 10},
        },
        "sys_interval": 0,
        "auth": {"allow-anonymous": True},
    }
    return broker_config


def _ports(broker):
    """Extract the OS-assigned ports from a running broker.

    Returns ``(mqtt_port, ws_port, wss_port, mqtt_uri)``.
    """
    mqtt_port = broker._servers["mqtt"].port  # noqa: SLF001
    ws_port = broker._servers["ws"].port  # noqa: SLF001
    wss_port = broker._servers["wss"].port  # noqa: SLF001
    uri = f"mqtt://127.0.0.1:{mqtt_port}/"
    return mqtt_port, ws_port, wss_port, uri


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
            # No broker is started; connecting to a privileged port where
            # nothing listens reliably triggers ConnectException.
            URI = "mqtt://127.0.0.1:1/"
            with pytest.raises(ConnectException), ungroup:
                async with open_mqttclient(config={"auto_reconnect": False}) as client:
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
            broker_config = _broker_config()
            async with (
                create_broker(broker_config, plugin_namespace="moat.mqtt.test.plugins") as broker,
                open_mqttclient() as client,
            ):
                _, WSPORT, _, _ = _ports(broker)
                await client.connect(f"ws://127.0.0.1:{WSPORT}/")
                assert client.session is not None

        anyio_run(test_coro, backend="trio")

    def test_reconnect_ws_retain_username_password(self):  # noqa: D102
        async def test_coro():
            broker_config = _broker_config()
            async with (
                create_broker(broker_config, plugin_namespace="moat.mqtt.test.plugins") as broker,
                open_mqttclient() as client,
            ):
                _, WSPORT, _, _ = _ports(broker)
                await client.connect(f"ws://fred:password@127.0.0.1:{WSPORT}/")
                assert client.session is not None
                await client.reconnect()

                assert client.session.username is not None
                assert client.session.password is not None

        anyio_run(test_coro, backend="trio")

    def test_connect_ws_secure(self):  # noqa: D102
        async def test_coro():
            broker_config = _broker_config()
            async with (
                create_broker(broker_config, plugin_namespace="moat.mqtt.test.plugins") as broker,
                open_mqttclient() as client,
            ):
                _, _, WSSPORT, _ = _ports(broker)
                ca = os.path.join(
                    os.path.dirname(os.path.realpath(__file__)),
                    "mosquitto.org.crt",
                )
                await client.connect(f"ws://127.0.0.1:{WSSPORT}/", cafile=ca)
                assert client.session is not None

        anyio_run(test_coro, backend="trio")

    def test_ping(self):  # noqa: D102
        async def test_coro():
            broker_config = _broker_config()
            async with (
                create_broker(broker_config, plugin_namespace="moat.mqtt.test.plugins") as broker,
                open_mqttclient() as client,
            ):
                _, _, _, URI = _ports(broker)
                await client.connect(URI)
                assert client.session is not None
                await client.ping()

        anyio_run(test_coro, backend="trio")

    def test_subscribe(self):  # noqa: D102
        async def test_coro():
            broker_config = _broker_config()
            async with (
                create_broker(broker_config, plugin_namespace="moat.mqtt.test.plugins") as broker,
                open_mqttclient() as client,
            ):
                _, _, _, URI = _ports(broker)
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
            broker_config = _broker_config()
            async with (
                create_broker(broker_config, plugin_namespace="moat.mqtt.test.plugins") as broker,
                open_mqttclient() as client,
            ):
                _, _, _, URI = _ports(broker)
                await client.connect(URI)
                assert client.session is not None
                ret = await client.subscribe([("$SYS/broker/uptime", QOS_0)])
                assert ret[0] == QOS_0
                await client.unsubscribe(["$SYS/broker/uptime"])

        anyio_run(test_coro, backend="trio")

    def test_deliver(self):  # noqa: D102
        data = b"data"

        async def test_coro():
            broker_config = _broker_config()
            async with (
                create_broker(broker_config, plugin_namespace="moat.mqtt.test.plugins") as broker,
                open_mqttclient() as client,
            ):
                _, _, _, URI = _ports(broker)
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
            broker_config = _broker_config()
            async with (
                create_broker(broker_config, plugin_namespace="moat.mqtt.test.plugins") as broker,
                open_mqttclient() as client,
            ):
                _, _, _, URI = _ports(broker)
                await client.connect(URI)
                assert client.session is not None
                ret = await client.subscribe([("test_topic", QOS_0)])
                assert ret[0] == QOS_0
                with pytest.raises(TimeoutError), anyio.fail_after(2):
                    await client.deliver_message()
                await client.unsubscribe(["$SYS/broker/uptime"])

        anyio_run(test_coro, backend="trio")
