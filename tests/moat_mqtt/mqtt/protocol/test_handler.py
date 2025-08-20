# Copyright (c) 2015 Nicolas JOUANIN
#
# See the file license.txt for copying permission.
from __future__ import annotations
import logging
import os
import random
import unittest
from functools import partial

import anyio

from moat.mqtt.adapters import StreamAdapter
from moat.mqtt.mqtt.constants import QOS_0, QOS_1, QOS_2
from moat.mqtt.mqtt.protocol.handler import ProtocolHandler
from moat.mqtt.mqtt.puback import PubackPacket
from moat.mqtt.mqtt.pubcomp import PubcompPacket
from moat.mqtt.mqtt.publish import PublishPacket
from moat.mqtt.mqtt.pubrec import PubrecPacket
from moat.mqtt.mqtt.pubrel import PubrelPacket
from moat.mqtt.plugins.manager import PluginManager
from moat.mqtt.session import (
    IncomingApplicationMessage,
    OutgoingApplicationMessage,
    Session,
)

from tests.moat_mqtt import anyio_run

log = logging.getLogger(__name__)


def rand_packet_id():
    return random.randint(0, 65535)


def adapt(conn):
    return StreamAdapter(conn)


class ProtocolHandlerTest(unittest.TestCase):
    handler = session = plugin_manager = None  # appease pylint
    listen_ctx = None

    async def listener_(self, server_mock, sock):
        if not hasattr(sock, "read"):
            sock.read = sock.receive
        if not hasattr(sock, "write"):
            sock.write = sock.send
        try:
            await server_mock(sock)
        finally:
            with anyio.fail_after(1, shield=True):
                await sock.aclose()

    def run_(self, server_mock, test_coro, port):
        async def runner():
            async with anyio.create_task_group() as tg:
                self.plugin_manager = PluginManager(tg, "moat.mqtt.test.plugins", context=None)
                server = await anyio.create_tcp_listener(local_port=port, local_host="127.0.0.1")

                async def _serve():
                    async with server:
                        await server.serve(partial(self.listener_, server_mock), task_group=tg)

                tg.start_soon(_serve)

                async with await anyio.connect_tcp("127.0.0.1", port) as conn:
                    sr = adapt(conn)
                    await test_coro(sr)
                    tg.cancel_scope.cancel()
                pass  # waiting for taskgroup

        anyio_run(runner)

    def test_start_stop(self, free_tcp_port):
        async def server_mock(stream):  # pylint: disable=unused-argument
            pass

        async def test_coro(stream_adapted):
            s = Session(None)
            handler = ProtocolHandler(self.plugin_manager)
            await handler.attach(s, stream_adapted)
            await self.start_handler(handler, s)
            await self.stop_handler(handler, s)

        self.run_(server_mock, test_coro, free_tcp_port)

    def test_publish_qos0(self, free_tcp_port):
        async def server_mock(stream):
            packet = await PublishPacket.from_stream(stream)
            assert packet.variable_header.topic_name == "/topic"
            assert packet.qos == QOS_0
            assert packet.packet_id is None

        async def test_coro(stream_adapted):
            s = Session(None)
            handler = ProtocolHandler(self.plugin_manager)
            await handler.attach(s, stream_adapted)
            await self.start_handler(handler, s)
            message = await handler.mqtt_publish("/topic", b"test_data", QOS_0, False)
            assert isinstance(message, OutgoingApplicationMessage)
            assert message.publish_packet is not None
            assert message.puback_packet is None
            assert message.pubrec_packet is None
            assert message.pubrel_packet is None
            assert message.pubcomp_packet is None
            await self.stop_handler(handler, s)

        self.run_(server_mock, test_coro, free_tcp_port)

    def test_publish_qos1(self, free_tcp_port):
        async def server_mock(stream):
            packet = await PublishPacket.from_stream(stream)
            assert packet.variable_header.topic_name == "/topic"
            assert packet.qos == QOS_1
            assert packet.packet_id is not None
            assert packet.packet_id in self.session.inflight_out
            assert packet.packet_id in self.handler._puback_waiters
            puback = PubackPacket.build(packet.packet_id)
            await puback.to_stream(stream)

        async def test_coro(stream_adapted):
            self.session = Session(None)
            self.handler = ProtocolHandler(self.plugin_manager)
            await self.handler.attach(self.session, stream_adapted)
            await self.start_handler(self.handler, self.session)
            message = await self.handler.mqtt_publish("/topic", b"test_data", QOS_1, False)
            assert isinstance(message, OutgoingApplicationMessage)
            assert message.publish_packet is not None
            assert message.puback_packet is not None
            assert message.pubrec_packet is None
            assert message.pubrel_packet is None
            assert message.pubcomp_packet is None
            await self.stop_handler(self.handler, self.session)

        self.handler = None
        self.run_(server_mock, test_coro, free_tcp_port)

    def test_publish_qos2(self, free_tcp_port):
        async def server_mock(stream):
            packet = await PublishPacket.from_stream(stream)
            assert packet.topic_name == "/topic"
            assert packet.qos == QOS_2
            assert packet.packet_id is not None
            assert packet.packet_id in self.session.inflight_out
            assert packet.packet_id in self.handler._pubrec_waiters
            pubrec = PubrecPacket.build(packet.packet_id)
            await pubrec.to_stream(stream)

            await PubrelPacket.from_stream(stream)
            assert packet.packet_id in self.handler._pubcomp_waiters
            pubcomp = PubcompPacket.build(packet.packet_id)
            await pubcomp.to_stream(stream)

        async def test_coro(stream_adapted):
            self.session = Session(None)
            self.handler = ProtocolHandler(self.plugin_manager)
            await self.handler.attach(self.session, stream_adapted)
            await self.start_handler(self.handler, self.session)
            message = await self.handler.mqtt_publish("/topic", b"test_data", QOS_2, False)
            assert isinstance(message, OutgoingApplicationMessage)
            assert message.publish_packet is not None
            assert message.puback_packet is None
            assert message.pubrec_packet is not None
            assert message.pubrel_packet is not None
            assert message.pubcomp_packet is not None
            await self.stop_handler(self.handler, self.session)

        self.handler = None

        self.run_(server_mock, test_coro, free_tcp_port)

    def test_receive_qos0(self, free_tcp_port):
        async def server_mock(stream):
            packet = PublishPacket.build(
                "/topic",
                b"test_data",
                rand_packet_id(),
                False,
                QOS_0,
                False,
            )
            await packet.to_stream(stream)

        async def test_coro(stream_adapted):
            self.session = Session(None)
            self.handler = ProtocolHandler(self.plugin_manager)
            await self.handler.attach(self.session, stream_adapted)
            await self.start_handler(self.handler, self.session)
            message = await self.session.get_next_message()
            assert isinstance(message, IncomingApplicationMessage)
            assert message.publish_packet is not None
            assert message.puback_packet is None
            assert message.pubrec_packet is None
            assert message.pubrel_packet is None
            assert message.pubcomp_packet is None
            await self.stop_handler(self.handler, self.session)

        self.handler = None
        self.run_(server_mock, test_coro, free_tcp_port)

    def test_receive_qos1(self, free_tcp_port):
        async def server_mock(stream):
            packet = PublishPacket.build(
                "/topic",
                b"test_data",
                rand_packet_id(),
                False,
                QOS_1,
                False,
            )
            await packet.to_stream(stream)
            puback = await PubackPacket.from_stream(stream)
            assert puback is not None
            assert packet.packet_id == puback.packet_id

        async def test_coro(stream_adapted):
            self.session = Session(None)
            self.handler = ProtocolHandler(self.plugin_manager)
            await self.handler.attach(self.session, stream_adapted)
            await self.start_handler(self.handler, self.session)
            await anyio.sleep(0.1)  # as below
            message = await self.session.get_next_message()
            assert isinstance(message, IncomingApplicationMessage)
            assert message.publish_packet is not None
            assert message.puback_packet is not None
            assert message.pubrec_packet is None
            assert message.pubrel_packet is None
            assert message.pubcomp_packet is None
            await self.stop_handler(self.handler, self.session)

        self.handler = None
        self.run_(server_mock, test_coro, free_tcp_port)

    def test_receive_qos2(self, free_tcp_port):
        async def server_mock(stream):
            packet = PublishPacket.build(
                "/topic",
                b"test_data",
                rand_packet_id(),
                False,
                QOS_2,
                False,
            )
            await packet.to_stream(stream)
            pubrec = await PubrecPacket.from_stream(stream)
            assert pubrec is not None
            assert packet.packet_id == pubrec.packet_id
            assert packet.packet_id in self.handler._pubrel_waiters
            pubrel = PubrelPacket.build(packet.packet_id)
            await pubrel.to_stream(stream)
            pubcomp = await PubcompPacket.from_stream(stream)
            assert pubcomp is not None
            assert packet.packet_id == pubcomp.packet_id

        async def test_coro(stream_adapted):
            self.session = Session(None)
            self.handler = ProtocolHandler(self.plugin_manager)
            await self.handler.attach(self.session, stream_adapted)
            await self.start_handler(self.handler, self.session)
            await anyio.sleep(0.1)  # the pubcomp packet is built *after* queueing
            message = await self.session.get_next_message()
            assert isinstance(message, IncomingApplicationMessage)
            assert message.publish_packet is not None
            assert message.puback_packet is None
            assert message.pubrec_packet is not None
            assert message.pubrel_packet is not None
            assert message.pubcomp_packet is not None  # might fail w/o the sleep
            await self.stop_handler(self.handler, self.session)

        self.handler = None
        self.run_(server_mock, test_coro, free_tcp_port)

    async def start_handler(self, handler, session):
        self.check_empty_waiters(handler)
        self.check_no_message(session)
        await handler.start()

    async def stop_handler(self, handler, session):
        await handler.stop()
        assert handler._reader_stopped
        self.check_empty_waiters(handler)
        self.check_no_message(session)

    def check_empty_waiters(self, handler):
        assert not handler._puback_waiters
        assert not handler._pubrec_waiters
        assert not handler._pubrel_waiters
        assert not handler._pubcomp_waiters

    def check_no_message(self, session):
        assert not session.inflight_out
        assert not session.inflight_in

    def test_publish_qos1_retry(self, free_tcp_port):
        async def server_mock(stream):
            packet = await PublishPacket.from_stream(stream)
            assert packet.topic_name == "/topic"
            assert packet.qos == QOS_1
            assert packet.packet_id is not None
            assert packet.packet_id in self.session.inflight_out
            assert packet.packet_id in self.handler._puback_waiters
            puback = PubackPacket.build(packet.packet_id)
            await puback.to_stream(stream)

        async def test_coro(stream_adapted):
            self.session = Session(None)
            message = OutgoingApplicationMessage(1, "/topic", QOS_1, b"test_data", False)
            message.publish_packet = PublishPacket.build(
                "/topic",
                b"test_data",
                rand_packet_id(),
                False,
                QOS_1,
                False,
            )
            self.session.inflight_out[1] = message
            self.handler = ProtocolHandler(self.plugin_manager)
            await self.handler.attach(self.session, stream_adapted)
            await self.handler.start()
            await self.stop_handler(self.handler, self.session)

        self.handler = None

        self.run_(server_mock, test_coro, free_tcp_port)

    def test_publish_qos2_retry(self, free_tcp_port):
        async def server_mock(stream):
            packet = await PublishPacket.from_stream(stream)
            assert packet.topic_name == "/topic"
            assert packet.qos == QOS_2
            assert packet.packet_id is not None
            assert packet.packet_id in self.session.inflight_out
            assert packet.packet_id in self.handler._pubrec_waiters
            pubrec = PubrecPacket.build(packet.packet_id)
            await pubrec.to_stream(stream)

            await PubrelPacket.from_stream(stream)
            assert packet.packet_id in self.handler._pubcomp_waiters
            pubcomp = PubcompPacket.build(packet.packet_id)
            await pubcomp.to_stream(stream)

        async def test_coro(stream_adapted):
            self.session = Session(None)
            message = OutgoingApplicationMessage(1, "/topic", QOS_2, b"test_data", False)
            message.publish_packet = PublishPacket.build(
                "/topic",
                b"test_data",
                rand_packet_id(),
                False,
                QOS_2,
                False,
            )
            self.session.inflight_out[1] = message
            self.handler = ProtocolHandler(self.plugin_manager)
            await self.handler.attach(self.session, stream_adapted)
            await self.handler.start()
            await self.stop_handler(self.handler, self.session)

        self.handler = None

        self.run_(server_mock, test_coro, free_tcp_port)
