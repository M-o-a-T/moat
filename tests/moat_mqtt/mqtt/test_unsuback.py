# Copyright (c) 2015 Nicolas JOUANIN
#
# See the file license.txt for copying permission.
from __future__ import annotations
import unittest

from moat.mqtt.adapters import BufferAdapter
from moat.mqtt.mqtt.packet import PacketIdVariableHeader
from moat.mqtt.mqtt.unsuback import UnsubackPacket

from tests.moat_mqtt import anyio_run


class UnsubackPacketTest(unittest.TestCase):
    def test_from_stream(self):
        data = b"\xb0\x02\x00\x0a"
        stream = BufferAdapter(data)
        message = anyio_run(UnsubackPacket.from_stream, stream)
        assert message.variable_header.packet_id == 10

    def test_to_stream(self):
        variable_header = PacketIdVariableHeader(10)
        publish = UnsubackPacket(variable_header=variable_header)
        out = publish.to_bytes()
        assert out == b"\xb0\x02\x00\n"
