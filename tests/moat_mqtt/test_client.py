# Copyright (c) 2015 Nicolas JOUANIN
#
# See the file license.txt for copying permission.
from __future__ import annotations
import logging
import os
import unittest

import anyio
import pytest

from moat.mqtt.broker import create_broker
from moat.util import ungroup
from moat.mqtt.client import ConnectException, open_mqttclient
from moat.mqtt.mqtt.constants import QOS_0, QOS_1, QOS_2

from . import anyio_run

log = logging.getLogger(__name__)

PORT = 40000 + (os.getpid() + 4) % 10000
URI = "mqtt://127.0.0.1:%d/" % PORT

broker_config = {
    "listeners": {
        "mqtt": {"type": "tcp", "bind": "127.0.0.1:%d" % PORT, "max_connections": 10},
        "ws": {"type": "ws", "bind": "127.0.0.1:8080", "max_connections": 10},
        "wss": {"type": "ws", "bind": "127.0.0.1:8081", "max_connections": 10},
    },
    "sys_interval": 0,
    "auth": {"allow-anonymous": True},
}


class MQTTClientTest(unittest.TestCase):
    @pytest.mark.xfail()
    def test_connect_tcp(self):
        async def test_coro():
            async with open_mqttclient() as client:
                await client.connect("mqtt://test.mosquitto.org/")
                assert client.session is not None

        try:
            anyio_run(test_coro)
        except ConnectException:
            log.error("Broken by server")

    @pytest.mark.xfail()
    def test_connect_tcp_secure(self):
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

    def test_connect_tcp_failure(self):
        async def test_coro():
            with pytest.raises(ConnectException), ungroup:
                config = {"auto_reconnect": False}
                async with open_mqttclient(config=config) as client:
                    await client.connect(URI)

        anyio_run(test_coro)

    @pytest.mark.xfail()
    def test_uri_supplied_early(self):
        config = {"auto_reconnect": False}

        async def test_coro():
            async with open_mqttclient("mqtt://test.mosquitto.org/", config=config) as client:
                assert client.session is not None

        try:
            anyio_run(test_coro)
        except ConnectException:
            log.error("Broken by server")

    def test_connect_ws(self):
        async def test_coro():
            async with create_broker(broker_config, plugin_namespace="moat.mqtt.test.plugins"):
                async with open_mqttclient() as client:
                    await client.connect("ws://127.0.0.1:8080/")
                    assert client.session is not None

        anyio_run(test_coro, backend="trio")

    def test_reconnect_ws_retain_username_password(self):
        async def test_coro():
            async with create_broker(broker_config, plugin_namespace="moat.mqtt.test.plugins"):
                async with open_mqttclient() as client:
                    await client.connect("ws://fred:password@127.0.0.1:8080/")
                    assert client.session is not None
                    await client.reconnect()

                    assert client.session.username is not None
                    assert client.session.password is not None

        anyio_run(test_coro, backend="trio")

    def test_connect_ws_secure(self):
        async def test_coro():
            async with create_broker(broker_config, plugin_namespace="moat.mqtt.test.plugins"):
                async with open_mqttclient() as client:
                    ca = os.path.join(
                        os.path.dirname(os.path.realpath(__file__)),
                        "mosquitto.org.crt",
                    )
                    await client.connect("ws://127.0.0.1:8081/", cafile=ca)
                    assert client.session is not None

        anyio_run(test_coro, backend="trio")

    def test_ping(self):
        async def test_coro():
            async with create_broker(broker_config, plugin_namespace="moat.mqtt.test.plugins"):
                async with open_mqttclient() as client:
                    await client.connect(URI)
                    assert client.session is not None
                    await client.ping()

        anyio_run(test_coro, backend="trio")

    def test_subscribe(self):
        async def test_coro():
            async with create_broker(broker_config, plugin_namespace="moat.mqtt.test.plugins"):
                async with open_mqttclient() as client:
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

    def test_unsubscribe(self):
        async def test_coro():
            async with create_broker(broker_config, plugin_namespace="moat.mqtt.test.plugins"):
                async with open_mqttclient() as client:
                    await client.connect(URI)
                    assert client.session is not None
                    ret = await client.subscribe([("$SYS/broker/uptime", QOS_0)])
                    assert ret[0] == QOS_0
                    await client.unsubscribe(["$SYS/broker/uptime"])

        anyio_run(test_coro, backend="trio")

    def test_deliver(self):
        data = b"data"

        async def test_coro():
            async with create_broker(broker_config, plugin_namespace="moat.mqtt.test.plugins"):
                async with open_mqttclient() as client:
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

    def test_deliver_timeout(self):
        async def test_coro():
            async with create_broker(broker_config, plugin_namespace="moat.mqtt.test.plugins"):
                async with open_mqttclient() as client:
                    await client.connect(URI)
                    assert client.session is not None
                    ret = await client.subscribe([("test_topic", QOS_0)])
                    assert ret[0] == QOS_0
                    with pytest.raises(TimeoutError), anyio.fail_after(2):
                        await client.deliver_message()
                    await client.unsubscribe(["$SYS/broker/uptime"])

        anyio_run(test_coro, backend="trio")
