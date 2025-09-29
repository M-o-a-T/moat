# Copyright (c) 2015 Nicolas JOUANIN  # noqa: D100
#
# See the file license.txt for copying permission.
from __future__ import annotations

import unittest

from tests.moat_mqtt import anyio_run

from moat.mqtt.adapters import BufferAdapter
from moat.mqtt.mqtt.packet import PacketIdVariableHeader
from moat.mqtt.mqtt.unsubscribe import UnsubscribePacket, UnubscribePayload


class UnsubscribePacketTest(unittest.TestCase):  # noqa: D101
    def test_from_stream(self):  # noqa: D102
        data = b"\xa2\x0c\x00\n\x00\x03a/b\x00\x03c/d"
        stream = BufferAdapter(data)
        message = anyio_run(UnsubscribePacket.from_stream, stream)
        assert message.payload.topics[0] == "a/b"
        assert message.payload.topics[1] == "c/d"

    def test_to_stream(self):  # noqa: D102
        variable_header = PacketIdVariableHeader(10)
        payload = UnubscribePayload(["a/b", "c/d"])
        publish = UnsubscribePacket(variable_header=variable_header, payload=payload)
        out = publish.to_bytes()
        assert out == b"\xa2\x0c\x00\n\x00\x03a/b\x00\x03c/d"
