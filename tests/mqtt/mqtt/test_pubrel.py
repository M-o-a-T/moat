# Copyright (c) 2015 Nicolas JOUANIN
#
# See the file license.txt for copying permission.
from __future__ import annotations
import unittest

from moat.mqtt.adapters import BufferAdapter
from moat.mqtt.mqtt.pubrel import PacketIdVariableHeader, PubrelPacket

from tests.mqtt import anyio_run


class PubrelPacketTest(unittest.TestCase):
    def test_from_stream(self):
        data = b"\x60\x02\x00\x0a"
        stream = BufferAdapter(data)
        message = anyio_run(PubrelPacket.from_stream, stream)
        assert message.variable_header.packet_id == 10

    def test_to_bytes(self):
        variable_header = PacketIdVariableHeader(10)
        publish = PubrelPacket(variable_header=variable_header)
        out = publish.to_bytes()
        assert out == b"b\x02\x00\n"
