# Copyright (c) 2015 Nicolas JOUANIN
#
# See the file license.txt for copying permission.
from __future__ import annotations
import unittest

from moat.mqtt.adapters import BufferAdapter
from moat.mqtt.errors import MQTTException
from moat.mqtt.mqtt.packet import CONNECT, MQTTFixedHeader

from tests.moat_mqtt import anyio_run
import pytest


class TestMQTTFixedHeaderTest(unittest.TestCase):
    def test_from_bytes(self):
        data = b"\x10\x7f"
        stream = BufferAdapter(data)
        header = anyio_run(MQTTFixedHeader.from_stream, stream)
        assert header.packet_type == CONNECT
        assert not header.flags & 8
        assert (header.flags & 6) >> 1 == 0
        assert not header.flags & 1
        assert header.remaining_length == 127

    def test_from_bytes_with_length(self):
        data = b"\x10\xff\xff\xff\x7f"
        stream = BufferAdapter(data)
        header = anyio_run(MQTTFixedHeader.from_stream, stream)
        assert header.packet_type == CONNECT
        assert not header.flags & 8
        assert (header.flags & 6) >> 1 == 0
        assert not header.flags & 1
        assert header.remaining_length == 268435455

    def test_from_bytes_ko_with_length(self):
        data = b"\x10\xff\xff\xff\xff\x7f"
        stream = BufferAdapter(data)
        with pytest.raises(MQTTException):
            anyio_run(MQTTFixedHeader.from_stream, stream)

    def test_to_bytes(self):
        header = MQTTFixedHeader(CONNECT, 0x00, 0)
        data = header.to_bytes()
        assert data == b"\x10\x00"

    def test_to_bytes_2(self):
        header = MQTTFixedHeader(CONNECT, 0x00, 268435455)
        data = header.to_bytes()
        assert data == b"\x10\xff\xff\xff\x7f"
