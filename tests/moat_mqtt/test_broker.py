# Copyright (c) 2015 Nicolas JOUANIN
#
# See the file license.txt for copying permission.
from __future__ import annotations
import logging
import os
import unittest
from unittest.mock import MagicMock, call, patch

import anyio
import pytest

from moat.mqtt.adapters import StreamAdapter
from moat.mqtt.broker import (
    EVENT_BROKER_CLIENT_SUBSCRIBED,
    EVENT_BROKER_CLIENT_UNSUBSCRIBED,
    EVENT_BROKER_MESSAGE_RECEIVED,
    EVENT_BROKER_POST_SHUTDOWN,
    EVENT_BROKER_POST_START,
    EVENT_BROKER_PRE_SHUTDOWN,
    EVENT_BROKER_PRE_START,
    create_broker,
)
from moat.mqtt.client import ConnectException, open_mqttclient
from moat.mqtt.mqtt import (
    ConnackPacket,
    ConnectPacket,
    DisconnectPacket,
    PublishPacket,
    PubrecPacket,
    PubrelPacket,
)
from moat.mqtt.mqtt.connect import ConnectPayload, ConnectVariableHeader
from moat.mqtt.mqtt.constants import QOS_0, QOS_1, QOS_2
from anyio.pytest_plugin import FreePortFactory
from socket import SOCK_STREAM

from . import anyio_run

log = logging.getLogger(__name__)

def _PUT():
    PORT = FreePortFactory(SOCK_STREAM)() 
    URL = f"mqtt://127.0.0.1:{PORT}/"
    test_config = {
        "listeners": {
            "default": {"type": "tcp", "bind": f"127.0.0.1:{PORT}", "max_connections": 10},
        },
        "sys_interval": 0,
        "auth": {"allow-anonymous": True},
    }
    return PORT,URL,test_config


class AsyncMock(MagicMock):
    def __await__(self):
        async def foo():
            return self

        return foo().__await__()


class BrokerTest(unittest.TestCase):
    @patch("moat.mqtt.broker.PluginManager", new_callable=AsyncMock)
    def test_start_stop(self, MockPluginManager):  # pylint: disable=unused-argument
        async def test_coro():
            _,URL,test_config = _PUT()
            async with create_broker(
                test_config,
                plugin_namespace="moat.mqtt.test.plugins",
            ) as broker:
                broker.plugins_manager._tg = broker._tg
                assert broker.transitions.is_started()
                self.assertDictEqual(broker._sessions, {})
                assert "default" in broker._servers
                MockPluginManager.assert_has_calls(
                    [
                        call().fire_event(EVENT_BROKER_PRE_START),
                        call().fire_event(EVENT_BROKER_POST_START),
                    ],
                    any_order=True,
                )
                MockPluginManager.reset_mock()
            MockPluginManager.assert_has_calls(
                [
                    call().fire_event(EVENT_BROKER_PRE_SHUTDOWN),
                    call().fire_event(EVENT_BROKER_POST_SHUTDOWN),
                ],
                any_order=True,
            )
            assert broker.transitions.is_stopped()

        anyio_run(test_coro, backend="trio")

    @patch("moat.mqtt.broker.PluginManager", new_callable=AsyncMock)
    def test_client_connect(self, MockPluginManager):  # pylint: disable=unused-argument
        async def test_coro():
            _,URL,test_config = _PUT()
            async with create_broker(
                test_config,
                plugin_namespace="moat.mqtt.test.plugins",
            ) as broker:
                broker.plugins_manager._tg = broker._tg
                assert broker.transitions.is_started()
                async with open_mqttclient() as client:
                    ret = await client.connect(URL)
                    assert ret == 0
                    assert len(broker._sessions) == 1
                    assert client.session.client_id in broker._sessions
                await anyio.sleep(0.1)  # let the broker task process the packet
            assert broker.transitions.is_stopped()
            self.assertDictEqual(broker._sessions, {})

        anyio_run(test_coro)

    @patch("moat.mqtt.broker.PluginManager", new_callable=AsyncMock)
    def test_client_connect_will_flag(self, MockPluginManager):  # pylint: disable=unused-argument
        async def test_coro():
            PORT,_,test_config = _PUT()
            async with create_broker(
                test_config,
                plugin_namespace="moat.mqtt.test.plugins",
            ) as broker:
                broker.plugins_manager._tg = broker._tg
                assert broker.transitions.is_started()

                async with await anyio.connect_tcp("127.0.0.1", PORT) as conn:
                    stream = StreamAdapter(conn)

                    vh = ConnectVariableHeader()
                    payload = ConnectPayload()

                    vh.keep_alive = 10
                    vh.clean_session_flag = False
                    vh.will_retain_flag = False
                    vh.will_flag = True
                    vh.will_qos = QOS_0
                    payload.client_id = "test_id"
                    payload.will_message = b"test"
                    payload.will_topic = "/topic"
                    connect = ConnectPacket(vh=vh, payload=payload)
                    await connect.to_stream(stream)
                    await ConnackPacket.from_stream(stream)

                    disconnect = DisconnectPacket()
                    await disconnect.to_stream(stream)

            assert broker.transitions.is_stopped()
            self.assertDictEqual(broker._sessions, {})

        anyio_run(test_coro, backend="trio")

    @patch("moat.mqtt.broker.PluginManager", new_callable=AsyncMock)
    def test_client_connect_clean_session_false(self, MockPluginManager):  # pylint: disable=unused-argument
        async def test_coro():
            _,URL,test_config = _PUT()
            async with create_broker(
                test_config,
                plugin_namespace="moat.mqtt.test.plugins",
            ) as broker:
                broker.plugins_manager._tg = broker._tg
                assert broker.transitions.is_started()
                async with open_mqttclient(
                    client_id="",
                    config={"auto_reconnect": False},
                ) as client:
                    return_code = None
                    with pytest.raises(ConnectException) as ce:
                        await client.connect(URL, cleansession=False)
                    return_code = ce.value.return_code
                    assert return_code == 2
                    assert client.session.client_id not in broker._sessions

        anyio_run(test_coro)

    @patch("moat.mqtt.broker.PluginManager", new_callable=AsyncMock)
    def test_client_subscribe(self, MockPluginManager):
        async def test_coro():
            _,URL,test_config = _PUT()
            async with create_broker(
                test_config,
                plugin_namespace="moat.mqtt.test.plugins",
            ) as broker:
                broker.plugins_manager._tg = broker._tg
                assert broker.transitions.is_started()
                async with open_mqttclient() as client:
                    ret = await client.connect(URL)
                    assert ret == 0
                    await client.subscribe([("/topic", QOS_0)])

                    # Test if the client test client subscription is registered
                    subs = broker._subscriptions[("", "topic")]
                    assert len(subs) == 1
                    (s, qos) = subs[0]
                    assert s == client.session
                    assert qos == QOS_0

            assert broker.transitions.is_stopped()
            MockPluginManager.assert_has_calls(
                [
                    call().fire_event(
                        EVENT_BROKER_CLIENT_SUBSCRIBED,
                        client_id=client.session.client_id,
                        topic="/topic",
                        qos=QOS_0,
                    ),
                ],
                any_order=True,
            )

        anyio_run(test_coro, backend="trio")

    @patch("moat.mqtt.broker.PluginManager", new_callable=AsyncMock)
    def test_client_subscribe_twice(self, MockPluginManager):
        async def test_coro():
            _,URL,test_config = _PUT()
            async with create_broker(
                test_config,
                plugin_namespace="moat.mqtt.test.plugins",
            ) as broker:
                broker.plugins_manager._tg = broker._tg
                assert broker.transitions.is_started()
                async with open_mqttclient() as client:
                    ret = await client.connect(URL)
                    assert ret == 0
                    await client.subscribe([("/topic", QOS_0)])

                    # Test if the client test client subscription is registered
                    subs = broker._subscriptions[("", "topic")]
                    assert len(subs) == 1
                    (s, qos) = subs[0]
                    assert s == client.session
                    assert qos == QOS_0

                    await client.subscribe([("/topic", QOS_0)])
                    assert len(subs) == 1
                    (s, qos) = subs[0]
                    assert s == client.session
                    assert qos == QOS_0

            assert broker.transitions.is_stopped()
            MockPluginManager.assert_has_calls(
                [
                    call().fire_event(
                        EVENT_BROKER_CLIENT_SUBSCRIBED,
                        client_id=client.session.client_id,
                        topic="/topic",
                        qos=QOS_0,
                    ),
                ],
                any_order=True,
            )

        anyio_run(test_coro, backend="trio")

    @patch("moat.mqtt.broker.PluginManager", new_callable=AsyncMock)
    def test_client_unsubscribe(self, MockPluginManager):
        async def test_coro():
            _,URL,test_config = _PUT()
            async with create_broker(
                test_config,
                plugin_namespace="moat.mqtt.test.plugins",
            ) as broker:
                broker.plugins_manager._tg = broker._tg
                assert broker.transitions.is_started()
                async with open_mqttclient() as client:
                    ret = await client.connect(URL)
                    assert ret == 0
                    await client.subscribe([("/topic", QOS_0)])

                    # Test if the client test client subscription is registered
                    subs = broker._subscriptions[("", "topic")]
                    assert len(subs) == 1
                    (s, qos) = subs[0]
                    assert s == client.session
                    assert qos == QOS_0

                    await client.unsubscribe(["/topic"])
                    assert broker._subscriptions["", "topic"] == []
            assert broker.transitions.is_stopped()
            MockPluginManager.assert_has_calls(
                [
                    call().fire_event(
                        EVENT_BROKER_CLIENT_SUBSCRIBED,
                        client_id=client.session.client_id,
                        topic="/topic",
                        qos=QOS_0,
                    ),
                    call().fire_event(
                        EVENT_BROKER_CLIENT_UNSUBSCRIBED,
                        client_id=client.session.client_id,
                        topic="/topic",
                    ),
                ],
                any_order=True,
            )

        anyio_run(test_coro, backend="trio")

    @patch("moat.mqtt.broker.PluginManager", new_callable=AsyncMock)
    def test_client_publish(self, MockPluginManager):
        async def test_coro():
            _,URL,test_config = _PUT()
            async with create_broker(
                test_config,
                plugin_namespace="moat.mqtt.test.plugins",
            ) as broker:
                broker.plugins_manager._tg = broker._tg
                assert broker.transitions.is_started()
                async with open_mqttclient() as pub_client:
                    ret = await pub_client.connect(URL)
                    assert ret == 0

                    ret_message = await pub_client.publish("/topic", b"data", QOS_0)
                await anyio.sleep(0.1)  # let the broker task process the packet
                assert broker._retained_messages == {}

            assert broker.transitions.is_stopped()
            MockPluginManager.assert_has_calls(
                [
                    call().fire_event(
                        EVENT_BROKER_MESSAGE_RECEIVED,
                        client_id=pub_client.session.client_id,
                        message=ret_message,
                    ),
                ],
                any_order=True,
            )

        anyio_run(test_coro)

    # @patch('moat.mqtt.broker.PluginManager', new_callable=AsyncMock)
    def test_client_publish_dup(self):
        async def test_coro():
            PORT,_,test_config = _PUT()
            async with create_broker(
                test_config,
                plugin_namespace="moat.mqtt.test.plugins",
            ) as broker:
                broker.plugins_manager._tg = broker._tg
                assert broker.transitions.is_started()

                async with await anyio.connect_tcp("127.0.0.1", PORT) as conn:
                    stream = StreamAdapter(conn)

                    vh = ConnectVariableHeader()
                    payload = ConnectPayload()

                    vh.keep_alive = 10
                    vh.clean_session_flag = False
                    vh.will_retain_flag = False
                    payload.client_id = "test_id"
                    connect = ConnectPacket(vh=vh, payload=payload)
                    await connect.to_stream(stream)
                    await ConnackPacket.from_stream(stream)

                    publish_1 = PublishPacket.build("/test", b"data", 1, False, QOS_2, False)
                    await publish_1.to_stream(stream)
                    await PubrecPacket.from_stream(stream)

                    publish_dup = PublishPacket.build("/test", b"data", 1, True, QOS_2, False)
                    await publish_dup.to_stream(stream)
                    await PubrecPacket.from_stream(stream)
                    pubrel = PubrelPacket.build(1)
                    await pubrel.to_stream(stream)
                    # await PubcompPacket.from_stream(stream)

                    disconnect = DisconnectPacket()
                    await disconnect.to_stream(stream)

        anyio_run(test_coro, backend="trio")

    @patch("moat.mqtt.broker.PluginManager", new_callable=AsyncMock)
    def test_client_publish_invalid_topic(self, MockPluginManager):  # pylint: disable=unused-argument
        async def test_coro():
            _,URL,test_config = _PUT()
            async with create_broker(
                test_config,
                plugin_namespace="moat.mqtt.test.plugins",
            ) as broker:
                broker.plugins_manager._tg = broker._tg
                assert broker.transitions.is_started()
                async with open_mqttclient() as pub_client:
                    ret = await pub_client.connect(URL)
                    assert ret == 0

                    await pub_client.publish("/+", b"data", QOS_0)

            assert broker.transitions.is_stopped()

        anyio_run(test_coro)

    @patch("moat.mqtt.broker.PluginManager", new_callable=AsyncMock)
    def test_client_publish_big(self, MockPluginManager):
        async def test_coro():
            _,URL,test_config = _PUT()
            async with create_broker(
                test_config,
                plugin_namespace="moat.mqtt.test.plugins",
            ) as broker:
                broker.plugins_manager._tg = broker._tg
                assert broker.transitions.is_started()
                async with open_mqttclient() as pub_client:
                    ret = await pub_client.connect(URL)
                    assert ret == 0

                    ret_message = await pub_client.publish(
                        "/topic",
                        bytearray(b"\x99" * 256 * 1024),
                        QOS_2,
                    )
                assert broker._retained_messages == {}

            assert broker.transitions.is_stopped()
            MockPluginManager.assert_has_calls(
                [
                    call().fire_event(
                        EVENT_BROKER_MESSAGE_RECEIVED,
                        client_id=pub_client.session.client_id,
                        message=ret_message,
                    ),
                ],
                any_order=True,
            )

        anyio_run(test_coro, backend="trio")

    @patch("moat.mqtt.broker.PluginManager", new_callable=AsyncMock)
    def test_client_publish_retain(self, MockPluginManager):  # pylint: disable=unused-argument
        async def test_coro():
            _,URL,test_config = _PUT()
            async with create_broker(
                test_config,
                plugin_namespace="moat.mqtt.test.plugins",
            ) as broker:
                broker.plugins_manager._tg = broker._tg
                assert broker.transitions.is_started()

                async with open_mqttclient() as pub_client:
                    ret = await pub_client.connect(URL)
                    assert ret == 0
                    await pub_client.publish("/topic", b"data", QOS_0, retain=True)
                await anyio.sleep(0.1)  # let the broker task process the packet
                assert "/topic" in broker._retained_messages
                retained_message = broker._retained_messages["/topic"]
                assert retained_message.source_session == pub_client.session
                assert retained_message.topic == "/topic"
                assert retained_message.data == b"data"
                assert retained_message.qos == QOS_0
            assert broker.transitions.is_stopped()

        anyio_run(test_coro)

    @patch("moat.mqtt.broker.PluginManager", new_callable=AsyncMock)
    def test_client_publish_retain_delete(self, MockPluginManager):  # pylint: disable=unused-argument
        async def test_coro():
            _,URL,test_config = _PUT()
            async with create_broker(
                test_config,
                plugin_namespace="moat.mqtt.test.plugins",
            ) as broker:
                broker.plugins_manager._tg = broker._tg
                assert broker.transitions.is_started()

                async with open_mqttclient() as pub_client:
                    ret = await pub_client.connect(URL)
                    assert ret == 0
                    await pub_client.publish("/topic", b"", QOS_0, retain=True)
                await anyio.sleep(0.1)  # let the broker task process the packet
                assert "/topic" not in broker._retained_messages
            assert broker.transitions.is_stopped()

        anyio_run(test_coro)

    @patch("moat.mqtt.broker.PluginManager", new_callable=AsyncMock)
    def test_client_subscribe_publish(self, MockPluginManager):  # pylint: disable=unused-argument
        async def test_coro():
            _,URL,test_config = _PUT()
            async with create_broker(
                test_config,
                plugin_namespace="moat.mqtt.test.plugins",
            ) as broker:
                broker.plugins_manager._tg = broker._tg
                assert broker.transitions.is_started()
                async with open_mqttclient() as sub_client:
                    await sub_client.connect(URL)
                    ret = await sub_client.subscribe(
                        [
                            ("/qos0", QOS_0),
                            ("/qos1", QOS_1),
                            ("/qos2", QOS_2),
                        ],
                    )
                    assert ret == [QOS_0, QOS_1, QOS_2]

                    await self._client_publish("/qos0", b"data", QOS_0, URL)
                    await self._client_publish("/qos1", b"data", QOS_1, URL)
                    await self._client_publish("/qos2", b"data", QOS_2, URL)
                    for qos in [QOS_0, QOS_1, QOS_2]:
                        message = await sub_client.deliver_message()
                        assert message is not None
                        assert message.topic == "/qos%s" % qos
                        assert message.data == b"data"
                        assert message.qos == qos
            assert broker.transitions.is_stopped()

        anyio_run(test_coro)

    @patch("moat.mqtt.broker.PluginManager", new_callable=AsyncMock)
    def test_client_subscribe_invalid(self, MockPluginManager):  # pylint: disable=unused-argument
        async def test_coro():
            _,URL,test_config = _PUT()
            async with create_broker(
                test_config,
                plugin_namespace="moat.mqtt.test.plugins",
            ) as broker:
                broker.plugins_manager._tg = broker._tg
                assert broker.transitions.is_started()
                async with open_mqttclient() as sub_client:
                    await sub_client.connect(URL)
                    ret = await sub_client.subscribe(
                        [
                            ("+", QOS_0),
                            ("+/tennis/#", QOS_0),
                            ("sport+", QOS_0),
                            ("sport/+/player1", QOS_0),
                        ],
                    )
                    assert ret == [QOS_0, QOS_0, 128, QOS_0]

            assert broker.transitions.is_stopped()

        anyio_run(test_coro, backend="trio")

    @patch("moat.mqtt.broker.PluginManager", new_callable=AsyncMock)
    def test_client_subscribe_publish_dollar_topic_1(self, MockPluginManager):  # pylint: disable=unused-argument
        async def test_coro():
            _,URL,test_config = _PUT()
            async with create_broker(
                test_config,
                plugin_namespace="moat.mqtt.test.plugins",
            ) as broker:
                broker.plugins_manager._tg = broker._tg
                assert broker.transitions.is_started()
                async with open_mqttclient() as sub_client:
                    await sub_client.connect(URL)
                    ret = await sub_client.subscribe([("#", QOS_0)])
                    assert ret == [QOS_0]

                    await self._client_publish("/topic", b"data", QOS_0, URL)
                    message = await sub_client.deliver_message()
                    assert message is not None

                    await self._client_publish("$topic", b"data", QOS_0, URL)
                    message = None
                    with pytest.raises(TimeoutError), anyio.fail_after(1):
                        message = await sub_client.deliver_message()
                    assert message is None
            assert broker.transitions.is_stopped()

        anyio_run(test_coro)

    @patch("moat.mqtt.broker.PluginManager", new_callable=AsyncMock)
    def test_client_subscribe_publish_dollar_topic_2(self, MockPluginManager):  # pylint: disable=unused-argument
        async def test_coro():
            _,URL,test_config = _PUT()
            async with create_broker(
                test_config,
                plugin_namespace="moat.mqtt.test.plugins",
            ) as broker:
                broker.plugins_manager._tg = broker._tg
                assert broker.transitions.is_started()
                async with open_mqttclient() as sub_client:
                    await sub_client.connect(URL)
                    ret = await sub_client.subscribe([("+/monitor/Clients", QOS_0)])
                    assert ret == [QOS_0]

                    await self._client_publish("test/monitor/Clients", b"data", QOS_0, URL)
                    message = await sub_client.deliver_message()
                    assert message is not None

                    await self._client_publish("$SYS/monitor/Clients", b"data", QOS_0, URL)
                    message = None
                    with pytest.raises(TimeoutError), anyio.fail_after(1):
                        message = await sub_client.deliver_message()
                    assert message is None
            assert broker.transitions.is_stopped()

        anyio_run(test_coro)

    @patch("moat.mqtt.broker.PluginManager", new_callable=AsyncMock)
    def test_client_publish_retain_subscribe(self, MockPluginManager):  # pylint: disable=unused-argument
        async def test_coro():
            _,URL,test_config = _PUT()
            async with create_broker(
                test_config,
                plugin_namespace="moat.mqtt.test.plugins",
            ) as broker:
                with anyio.fail_after(3):
                    broker.plugins_manager._tg = broker._tg
                    assert broker.transitions.is_started()
                    async with open_mqttclient() as sub_client:
                        await sub_client.connect(URL, cleansession=False)
                        ret = await sub_client.subscribe(
                            [
                                ("/qos0", QOS_0),
                                ("/qos1", QOS_1),
                                ("/qos2", QOS_2),
                            ],
                        )
                        assert ret == [QOS_0, QOS_1, QOS_2]
                        await sub_client.disconnect()

                        await self._client_publish("/qos0", b"data", QOS_0, URL, retain=True)
                        await self._client_publish("/qos1", b"data", QOS_1, URL, retain=True)
                        await self._client_publish("/qos2", b"data", QOS_2, URL, retain=True)
                        await sub_client.reconnect()
                        seen = set()
                        for qos in [QOS_1, QOS_2]:
                            log.error("TEST QOS: %d", qos)
                            message = await sub_client.deliver_message()
                            log.error("Message: %r", message.publish_packet)
                            assert message.topic == f"/qos{qos}"
                            assert message.data == b"data"
                            seen.add(qos)
                        assert seen == set((1, 2))
            assert broker.transitions.is_stopped()

        anyio_run(test_coro)

    async def _client_publish(self, topic, data, qos, URL, retain=False):
        async with open_mqttclient() as pub_client:
            ret = await pub_client.connect(URL)
            assert ret == 0
            ret = await pub_client.publish(topic, data, qos, retain)
        return ret
