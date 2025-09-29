# Copyright (c) 2015 Nicolas JOUANIN  # noqa: D100
#
# See the file license.txt for copying permission.
from __future__ import annotations

import unittest

from tests.moat_mqtt import anyio_run

from moat.mqtt.adapters import BufferAdapter
from moat.mqtt.mqtt.pubrec import PacketIdVariableHeader, PubrecPacket


class PubrecPacketTest(unittest.TestCase):  # noqa: D101
    def test_from_stream(self):  # noqa: D102
        data = b"\x50\x02\x00\x0a"
        stream = BufferAdapter(data)
        message = anyio_run(PubrecPacket.from_stream, stream)
        assert message.variable_header.packet_id == 10

    def test_to_bytes(self):  # noqa: D102
        variable_header = PacketIdVariableHeader(10)
        publish = PubrecPacket(variable_header=variable_header)
        out = publish.to_bytes()
        assert out == b"P\x02\x00\n"
