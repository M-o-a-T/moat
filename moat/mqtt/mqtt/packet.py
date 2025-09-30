# Copyright (c) 2015 Nicolas JOUANIN  # noqa: D100
#
# See the file license.txt for copying permission.
from __future__ import annotations

from datetime import UTC, datetime

from moat.mqtt.codecs import bytes_to_hex_str, decode_packet_id, int_to_bytes, read_or_raise
from moat.mqtt.errors import CodecException, MQTTException, NoDataException

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import anyio

    from moat.mqtt.adapters import StreamAdapter

RESERVED_0 = 0x00
CONNECT = 0x01
CONNACK = 0x02
PUBLISH = 0x03
PUBACK = 0x04
PUBREC = 0x05
PUBREL = 0x06
PUBCOMP = 0x07
SUBSCRIBE = 0x08
SUBACK = 0x09
UNSUBSCRIBE = 0x0A
UNSUBACK = 0x0B
PINGREQ = 0x0C
PINGRESP = 0x0D
DISCONNECT = 0x0E
RESERVED_15 = 0x0F


class MQTTFixedHeader:  # noqa: D101
    __slots__ = ("flags", "packet_type", "remaining_length")

    def __init__(self, packet_type, flags=0, length=0):
        self.packet_type = packet_type
        self.remaining_length = length
        self.flags = flags

    def to_bytes(self):  # noqa: D102
        def encode_remaining_length(length: int):
            encoded = bytearray()
            while True:
                length_byte = length % 0x80
                length //= 0x80
                if length > 0:
                    length_byte |= 0x80
                encoded.append(length_byte)
                if length <= 0:
                    break
            return encoded

        out = bytearray()
        packet_type = 0
        try:
            packet_type = (self.packet_type << 4) | self.flags
            out.append(packet_type)
        except OverflowError:
            raise CodecException(  # pylint:disable=W0707 # noqa:B904
                "packet_type encoding exceed 1 byte length: value=%d" % (packet_type,),
            )

        encoded_length = encode_remaining_length(self.remaining_length)
        out.extend(encoded_length)

        return out

    async def to_stream(self, writer: StreamAdapter):  # noqa: D102
        await writer.write(self.to_bytes())

    @property
    def bytes_length(self):  # noqa: D102
        return len(self.to_bytes())

    @classmethod
    async def from_stream(cls, reader: StreamAdapter):
        """
        Read and decode MQTT message fixed header from stream
        :return: FixedHeader instance
        """

        async def decode_remaining_length():
            """
            Decode message length according to MQTT specifications
            :return:
            """
            shift = 0
            value = 0
            buffer = bytearray()
            while True:
                int_byte = (await reader.read(1))[0]
                buffer.append(int_byte)
                value |= (int_byte & 0x7F) << shift
                if int_byte & 0x80:
                    shift += 7
                    if shift > 21:
                        raise MQTTException(
                            "Invalid remaining length bytes:%s, packet_type=%d"
                            % (bytes_to_hex_str(buffer), msg_type),
                        )
                else:
                    break
            return value

        try:
            int1 = (await read_or_raise(reader, 1))[0]
            msg_type = int1 >> 4
            flags = int1 & 0x0F
            remain_length = await decode_remaining_length()

            return cls(msg_type, flags, remain_length)
        except NoDataException:
            return None

    def __repr__(self):
        return type(self).__name__ + f"(length={self.remaining_length}, flags={hex(self.flags)})"


class MQTTVariableHeader:  # noqa: D101
    def __init__(self):
        pass

    async def to_stream(self, writer: anyio.abc.ByteStream):  # noqa: D102
        await writer.write(self.to_bytes())

    def to_bytes(self) -> bytes:
        """
        Serialize header data to a byte array conforming to MQTT protocol
        :return: serialized data
        """

    @property
    def bytes_length(self):  # noqa: D102
        return len(self.to_bytes())

    @classmethod
    async def from_stream(cls, reader: StreamAdapter, fixed_header: MQTTFixedHeader):  # noqa: D102
        pass


class PacketIdVariableHeader(MQTTVariableHeader):  # noqa: D101
    __slots__ = ("packet_id",)

    def __init__(self, packet_id):
        super().__init__()
        self.packet_id = packet_id

    def to_bytes(self):  # noqa: D102
        out = b""
        out += int_to_bytes(self.packet_id, 2)
        return out

    @classmethod
    async def from_stream(cls, reader: StreamAdapter, fixed_header: MQTTFixedHeader):  # noqa: ARG003, D102
        packet_id = await decode_packet_id(reader)
        return cls(packet_id)

    def __repr__(self):
        return type(self).__name__ + f"(packet_id={self.packet_id})"


class MQTTPayload:  # noqa: D101
    def __init__(self):
        pass

    def to_bytes(self, fixed_header: MQTTFixedHeader, variable_header: MQTTVariableHeader):  # noqa: D102
        raise NotImplementedError

    @classmethod
    async def from_stream(  # noqa: D102
        cls,
        reader: anyio.abc.ByteStream,
        fixed_header: MQTTFixedHeader,
        variable_header: MQTTVariableHeader,
    ):
        pass


class MQTTPacket:  # noqa: D101
    __slots__ = ("fixed_header", "payload", "protocol_ts", "variable_header")

    FIXED_HEADER = MQTTFixedHeader
    VARIABLE_HEADER = None
    PAYLOAD = None

    def __init__(
        self,
        fixed: MQTTFixedHeader,
        variable_header: MQTTVariableHeader = None,
        payload: MQTTPayload = None,
    ):
        self.fixed_header = fixed
        self.variable_header = variable_header
        self.payload = payload
        self.protocol_ts = None

    async def to_stream(self, writer: anyio.abc.ByteStream):  # noqa: D102
        await writer.write(self.to_bytes())
        self.protocol_ts = datetime.now(tz=UTC)

    def to_bytes(self) -> bytes:  # noqa: D102
        if self.variable_header:
            variable_header_bytes = self.variable_header.to_bytes()
        else:
            variable_header_bytes = b""
        if self.payload:
            payload_bytes = self.payload.to_bytes(self.fixed_header, self.variable_header)
        else:
            payload_bytes = b""

        self.fixed_header.remaining_length = len(variable_header_bytes) + len(payload_bytes)
        fixed_header_bytes = self.fixed_header.to_bytes()

        return fixed_header_bytes + variable_header_bytes + payload_bytes

    @classmethod
    async def from_stream(cls, reader: StreamAdapter, fixed_header=None, variable_header=None):  # noqa: D102
        if fixed_header is None:
            fixed_header = await cls.FIXED_HEADER.from_stream(reader)
        if variable_header is None and cls.VARIABLE_HEADER:
            variable_header = await cls.VARIABLE_HEADER.from_stream(reader, fixed_header)
        if cls.PAYLOAD:
            payload = await cls.PAYLOAD.from_stream(reader, fixed_header, variable_header)
        else:
            payload = None

        if payload:
            instance = cls(fixed_header, variable_header, payload)
        elif variable_header:
            instance = cls(fixed_header, variable_header)
        else:
            instance = cls(fixed_header)
        instance.protocol_ts = datetime.now(tz=UTC)
        return instance

    @property
    def bytes_length(self):  # noqa: D102
        return len(self.to_bytes())

    def __repr__(self):
        return (
            type(
                self,
            ).__name__
            + f"(ts={self.protocol_ts!s}, fixed={self.fixed_header!r}, variable={self.variable_header!r}, payload={self.payload!r})"
        )
