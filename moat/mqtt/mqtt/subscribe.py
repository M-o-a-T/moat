# Copyright (c) 2015 Nicolas JOUANIN  # noqa: D100
#
# See the file license.txt for copying permission.
from __future__ import annotations

from moat.mqtt.codecs import (
    bytes_to_int,
    decode_string,
    encode_string,
    int_to_bytes,
    read_or_raise,
)
from moat.mqtt.errors import MoatMQTTException, NoDataException

from .packet import (
    SUBSCRIBE,
    MQTTFixedHeader,
    MQTTPacket,
    MQTTPayload,
    MQTTVariableHeader,
    PacketIdVariableHeader,
)

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import anyio


class SubscribePayload(MQTTPayload):  # noqa: D101
    __slots__ = ("topics",)

    def __init__(self, topics=()):
        super().__init__()
        self.topics = topics

    def to_bytes(self, fixed_header: MQTTFixedHeader, variable_header: MQTTVariableHeader):  # noqa: ARG002, D102
        out = b""
        for topic in self.topics:
            out += encode_string(topic[0])
            out += int_to_bytes(topic[1], 1)
        return out

    @classmethod
    async def from_stream(  # noqa: D102
        cls,
        reader: anyio.abc.ByteStream,
        fixed_header: MQTTFixedHeader,
        variable_header: MQTTVariableHeader,
    ):
        topics = []
        payload_length = fixed_header.remaining_length - variable_header.bytes_length
        read_bytes = 0
        while read_bytes < payload_length:
            try:
                topic = await decode_string(reader)
                qos_byte = await read_or_raise(reader, 1)
                qos = bytes_to_int(qos_byte)
                topics.append((topic, qos))
                read_bytes += 2 + len(topic.encode("utf-8")) + 1
            except NoDataException:
                break
        return cls(topics)

    def __repr__(self):
        return type(self).__name__ + f"(topics={self.topics!r})"


class SubscribePacket(MQTTPacket):  # noqa: D101
    VARIABLE_HEADER = PacketIdVariableHeader
    PAYLOAD = SubscribePayload

    def __init__(
        self,
        fixed: MQTTFixedHeader = None,
        variable_header: PacketIdVariableHeader = None,
        payload=None,
    ):
        if fixed is None:
            header = MQTTFixedHeader(SUBSCRIBE, 0x02)  # [MQTT-3.8.1-1]
        else:
            if fixed.packet_type != SUBSCRIBE:
                raise MoatMQTTException(
                    f"Invalid fixed packet type {fixed.packet_type} for SubscribePacket init",
                )
            header = fixed

        super().__init__(header)
        self.variable_header = variable_header
        self.payload = payload

    @classmethod
    def build(cls, topics, packet_id):  # noqa: D102
        v_header = PacketIdVariableHeader(packet_id)
        payload = SubscribePayload(topics)
        return SubscribePacket(variable_header=v_header, payload=payload)
