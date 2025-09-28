# Copyright (c) 2015 Nicolas JOUANIN  # noqa: D100
#
# See the file license.txt for copying permission.
from __future__ import annotations

from moat.mqtt.codecs import read_or_raise
from moat.mqtt.errors import MoatMQTTException

from .packet import CONNACK, MQTTFixedHeader, MQTTPacket, MQTTVariableHeader

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.mqtt.adapters import StreamAdapter

CONNECTION_ACCEPTED = 0x00
UNACCEPTABLE_PROTOCOL_VERSION = 0x01
IDENTIFIER_REJECTED = 0x02
SERVER_UNAVAILABLE = 0x03
BAD_USERNAME_PASSWORD = 0x04
NOT_AUTHORIZED = 0x05
CLIENT_ERROR = 0x7F


class ConnackVariableHeader(MQTTVariableHeader):  # noqa: D101
    __slots__ = ("return_code", "session_parent")

    def __init__(self, session_parent=None, return_code=None):
        super().__init__()
        self.session_parent = session_parent
        self.return_code = return_code

    @classmethod
    async def from_stream(cls, reader: StreamAdapter, fixed_header: MQTTFixedHeader):  # noqa: ARG003, D102
        data = await read_or_raise(reader, 2)
        session_parent = data[0] & 0x01
        return_code = data[1]
        return cls(session_parent, return_code)

    def to_bytes(self):  # noqa: D102
        out = bytearray(2)
        # Connect acknowledge flags
        if self.session_parent:
            out[0] = 1
        else:
            out[0] = 0
        # return code
        out[1] = self.return_code

        return out

    def __repr__(self):
        return (
            type(self).__name__
            + f"(session_parent={hex(self.session_parent)}, return_code={hex(self.return_code)})"
        )


class ConnackPacket(MQTTPacket):  # noqa: D101
    VARIABLE_HEADER = ConnackVariableHeader
    PAYLOAD = None

    @property
    def return_code(self):  # noqa: D102
        return self.variable_header.return_code

    @return_code.setter
    def return_code(self, return_code):
        self.variable_header.return_code = return_code

    @property
    def session_parent(self):  # noqa: D102
        return self.variable_header.session_parent

    @session_parent.setter
    def session_parent(self, session_parent):
        self.variable_header.session_parent = session_parent

    def __init__(
        self,
        fixed: MQTTFixedHeader = None,
        variable_header: ConnackVariableHeader = None,
        payload=None,  # noqa: ARG002
    ):
        if fixed is None:
            header = MQTTFixedHeader(CONNACK, 0x00)
        else:
            if fixed.packet_type != CONNACK:
                raise MoatMQTTException(
                    f"Invalid fixed packet type {fixed.packet_type} for ConnackPacket init",
                )
            header = fixed
        super().__init__(header)
        self.variable_header = variable_header
        self.payload = None

    @classmethod
    def build(cls, session_parent=None, return_code=None):  # noqa: D102
        v_header = ConnackVariableHeader(session_parent, return_code)
        packet = ConnackPacket(variable_header=v_header)
        return packet
