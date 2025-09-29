# Copyright (c) 2015 Nicolas JOUANIN  # noqa: D100
#
# See the file license.txt for copying permission.
from __future__ import annotations

import unittest

from tests.moat_mqtt import anyio_run

from moat.mqtt.adapters import BufferAdapter
from moat.mqtt.mqtt.constants import QOS_0, QOS_1, QOS_2
from moat.mqtt.mqtt.publish import PublishPacket, PublishPayload, PublishVariableHeader


class PublishPacketTest(unittest.TestCase):  # noqa: D101
    def test_from_stream_qos_0(self):  # noqa: D102
        data = b"\x31\x11\x00\x05topic0123456789"
        stream = BufferAdapter(data)
        message = anyio_run(PublishPacket.from_stream, stream)
        assert message.variable_header.topic_name == "topic"
        assert message.variable_header.packet_id is None
        assert not message.fixed_header.flags >> 1 & 3
        assert message.fixed_header.flags & 1
        assert message.payload.data, b"0123456789"

    def test_from_stream_qos_2(self):  # noqa: D102
        data = b"\x37\x13\x00\x05topic\x00\x0a0123456789"
        stream = BufferAdapter(data)
        message = anyio_run(PublishPacket.from_stream, stream)
        assert message.variable_header.topic_name == "topic"
        assert message.variable_header.packet_id == 10
        assert message.fixed_header.flags >> 1 & 3
        assert message.fixed_header.flags & 1
        assert message.payload.data, b"0123456789"

    def test_to_stream_no_packet_id(self):  # noqa: D102
        variable_header = PublishVariableHeader("topic", None)
        payload = PublishPayload(b"0123456789")
        publish = PublishPacket(variable_header=variable_header, payload=payload)
        out = publish.to_bytes()
        assert out == b"0\x11\x00\x05topic0123456789"

    def test_to_stream_packet(self):  # noqa: D102
        variable_header = PublishVariableHeader("topic", 10)
        payload = PublishPayload(b"0123456789")
        publish = PublishPacket(variable_header=variable_header, payload=payload)
        out = publish.to_bytes()
        assert out == b"0\x13\x00\x05topic\x00\n0123456789"

    def test_build(self):  # noqa: D102
        packet = PublishPacket.build("/topic", b"data", 1, False, QOS_0, False)
        assert packet.packet_id == 1
        assert not packet.dup_flag
        assert packet.qos == QOS_0
        assert not packet.retain_flag

        packet = PublishPacket.build("/topic", b"data", 1, False, QOS_1, False)
        assert packet.packet_id == 1
        assert not packet.dup_flag
        assert packet.qos == QOS_1
        assert not packet.retain_flag

        packet = PublishPacket.build("/topic", b"data", 1, False, QOS_2, False)
        assert packet.packet_id == 1
        assert not packet.dup_flag
        assert packet.qos == QOS_2
        assert not packet.retain_flag

        packet = PublishPacket.build("/topic", b"data", 1, True, QOS_0, False)
        assert packet.packet_id == 1
        assert packet.dup_flag
        assert packet.qos == QOS_0
        assert not packet.retain_flag

        packet = PublishPacket.build("/topic", b"data", 1, True, QOS_1, False)
        assert packet.packet_id == 1
        assert packet.dup_flag
        assert packet.qos == QOS_1
        assert not packet.retain_flag

        packet = PublishPacket.build("/topic", b"data", 1, True, QOS_2, False)
        assert packet.packet_id == 1
        assert packet.dup_flag
        assert packet.qos == QOS_2
        assert not packet.retain_flag

        packet = PublishPacket.build("/topic", b"data", 1, False, QOS_0, True)
        assert packet.packet_id == 1
        assert not packet.dup_flag
        assert packet.qos == QOS_0
        assert packet.retain_flag

        packet = PublishPacket.build("/topic", b"data", 1, False, QOS_1, True)
        assert packet.packet_id == 1
        assert not packet.dup_flag
        assert packet.qos == QOS_1
        assert packet.retain_flag

        packet = PublishPacket.build("/topic", b"data", 1, False, QOS_2, True)
        assert packet.packet_id == 1
        assert not packet.dup_flag
        assert packet.qos == QOS_2
        assert packet.retain_flag

        packet = PublishPacket.build("/topic", b"data", 1, True, QOS_0, True)
        assert packet.packet_id == 1
        assert packet.dup_flag
        assert packet.qos == QOS_0
        assert packet.retain_flag

        packet = PublishPacket.build("/topic", b"data", 1, True, QOS_1, True)
        assert packet.packet_id == 1
        assert packet.dup_flag
        assert packet.qos == QOS_1
        assert packet.retain_flag

        packet = PublishPacket.build("/topic", b"data", 1, True, QOS_2, True)
        assert packet.packet_id == 1
        assert packet.dup_flag
        assert packet.qos == QOS_2
        assert packet.retain_flag
