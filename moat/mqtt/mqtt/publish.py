# Copyright (c) 2015 Nicolas JOUANIN  # noqa: D100
#
# See the file license.txt for copying permission.
from __future__ import annotations

from moat.mqtt.codecs import decode_packet_id, decode_string, encode_string, int_to_bytes
from moat.mqtt.errors import MoatMQTTException, MQTTException

from .packet import (
    PUBLISH,
    MQTTFixedHeader,
    MQTTPacket,
    MQTTPayload,
    MQTTVariableHeader,
)

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import anyio


class PublishVariableHeader(MQTTVariableHeader):  # noqa: D101
    __slots__ = ("packet_id", "topic_name")

    def __init__(self, topic_name: str, packet_id: int | None = None):
        super().__init__()
        if "*" in topic_name:
            raise MQTTException(
                "[MQTT-3.3.2-2] Topic name in the PUBLISH Packet MUST NOT contain wildcard characters.",
            )
        if not isinstance(topic_name, str):
            topic_name = "/".join(topic_name)
        self.topic_name = topic_name
        self.packet_id = packet_id

    def __repr__(self):
        return type(self).__name__ + f"(topic={self.topic_name}, packet_id={self.packet_id})"

    def to_bytes(self):  # noqa: D102
        out = bytearray()
        out.extend(encode_string(self.topic_name))
        if self.packet_id is not None:
            out.extend(int_to_bytes(self.packet_id, 2))
        return out

    @classmethod
    async def from_stream(cls, reader: anyio.abc.ByteStream, fixed_header: MQTTFixedHeader):  # noqa: D102
        topic_name = await decode_string(reader)
        has_qos = (fixed_header.flags >> 1) & 0x03
        if has_qos:
            packet_id = await decode_packet_id(reader)
        else:
            packet_id = None
        return cls(topic_name, packet_id)


class PublishPayload(MQTTPayload):  # noqa: D101
    __slots__ = ("data",)

    def __init__(self, data: bytes | None = None):
        super().__init__()
        self.data = data

    def to_bytes(self, fixed_header: MQTTFixedHeader, variable_header: MQTTVariableHeader):  # noqa: ARG002, D102
        return self.data

    @classmethod
    async def from_stream(  # noqa: D102
        cls,
        reader: anyio.abc.ByteStream,
        fixed_header: MQTTFixedHeader,
        variable_header: MQTTVariableHeader,
    ):
        data = bytearray()
        data_length = fixed_header.remaining_length - variable_header.bytes_length
        length_read = 0
        while length_read < data_length:
            buffer = await reader.read(data_length - length_read)
            data.extend(buffer)
            length_read = len(data)
        return cls(data)

    def __repr__(self):
        return type(self).__name__ + f"(data={repr(self.data)!r})"


class PublishPacket(MQTTPacket):  # noqa: D101
    VARIABLE_HEADER = PublishVariableHeader
    PAYLOAD = PublishPayload

    DUP_FLAG = 0x08
    RETAIN_FLAG = 0x01
    QOS_FLAG = 0x06

    def __init__(
        self,
        fixed: MQTTFixedHeader = None,
        variable_header: PublishVariableHeader = None,
        payload=None,
    ):
        if fixed is None:
            header = MQTTFixedHeader(PUBLISH, 0x00)
        else:
            if fixed.packet_type != PUBLISH:
                raise MoatMQTTException(
                    f"Invalid fixed packet type {fixed.packet_type} for PublishPacket init",
                )
            header = fixed

        super().__init__(header)
        self.variable_header = variable_header
        self.payload = payload

    def set_flags(self, dup_flag=False, qos=0, retain_flag=False):  # noqa: D102
        self.dup_flag = dup_flag
        self.retain_flag = retain_flag
        self.qos = qos

    def _set_header_flag(self, val, mask):
        if val:
            self.fixed_header.flags |= mask
        else:
            self.fixed_header.flags &= ~mask

    def _get_header_flag(self, mask):
        return bool(self.fixed_header.flags & mask)

    @property
    def dup_flag(self) -> bool:  # noqa: D102
        return self._get_header_flag(self.DUP_FLAG)

    @dup_flag.setter
    def dup_flag(self, val: bool):
        self._set_header_flag(val, self.DUP_FLAG)

    @property
    def retain_flag(self) -> bool:  # noqa: D102
        return self._get_header_flag(self.RETAIN_FLAG)

    @retain_flag.setter
    def retain_flag(self, val: bool):
        self._set_header_flag(val, self.RETAIN_FLAG)

    @property
    def qos(self):  # noqa: D102
        return (self.fixed_header.flags & self.QOS_FLAG) >> 1

    @qos.setter
    def qos(self, val: int):
        self.fixed_header.flags &= 0xF9
        self.fixed_header.flags |= val << 1

    @property
    def packet_id(self):  # noqa: D102
        return self.variable_header.packet_id

    @packet_id.setter
    def packet_id(self, val: int):
        self.variable_header.packet_id = val

    @property
    def data(self):  # noqa: D102
        return self.payload.data

    @data.setter
    def data(self, data: bytes):
        self.payload.data = data

    @property
    def topic_name(self):  # noqa: D102
        return self.variable_header.topic_name

    @topic_name.setter
    def topic_name(self, name: str):
        self.variable_header.topic_name = name

    @classmethod
    def build(cls, topic_name: str, message: bytes, packet_id: int, dup_flag, qos, retain):  # noqa: D102
        v_header = PublishVariableHeader(topic_name, packet_id)
        payload = PublishPayload(message)
        packet = PublishPacket(variable_header=v_header, payload=payload)
        packet.dup_flag = dup_flag
        packet.retain_flag = retain
        packet.qos = qos
        return packet
