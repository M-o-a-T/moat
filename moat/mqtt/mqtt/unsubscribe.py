# Copyright (c) 2015 Nicolas JOUANIN  # noqa: D100
#
# See the file license.txt for copying permission.
from __future__ import annotations

from moat.mqtt.codecs import decode_string, encode_string
from moat.mqtt.errors import MoatMQTTException, NoDataException

from .packet import (
    UNSUBSCRIBE,
    MQTTFixedHeader,
    MQTTPacket,
    MQTTPayload,
    MQTTVariableHeader,
    PacketIdVariableHeader,
)

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import anyio


class UnubscribePayload(MQTTPayload):  # noqa: D101
    __slots__ = ("topics",)

    def __init__(self, topics=()):
        super().__init__()
        self.topics = topics

    def to_bytes(self, fixed_header: MQTTFixedHeader, variable_header: MQTTVariableHeader):  # noqa: ARG002, D102
        out = b""
        for topic in self.topics:
            out += encode_string(topic)
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
                topics.append(topic)
                read_bytes += 2 + len(topic.encode("utf-8"))
            except NoDataException:
                break
        return cls(topics)


class UnsubscribePacket(MQTTPacket):  # noqa: D101
    VARIABLE_HEADER = PacketIdVariableHeader
    PAYLOAD = UnubscribePayload

    def __init__(
        self,
        fixed: MQTTFixedHeader = None,
        variable_header: PacketIdVariableHeader = None,
        payload=None,
    ):
        if fixed is None:
            header = MQTTFixedHeader(UNSUBSCRIBE, 0x02)  # [MQTT-3.10.1-1]
        else:
            if fixed.packet_type != UNSUBSCRIBE:
                raise MoatMQTTException(
                    f"Invalid fixed packet type {fixed.packet_type} for UnsubscribePacket init",
                )
            header = fixed

        super().__init__(header)
        self.variable_header = variable_header
        self.payload = payload

    @classmethod
    def build(cls, topics, packet_id):  # noqa: D102
        v_header = PacketIdVariableHeader(packet_id)
        payload = UnubscribePayload(topics)
        return UnsubscribePacket(variable_header=v_header, payload=payload)
