# Copyright (c) 2015 Nicolas JOUANIN  # noqa: D100
#
# See the file license.txt for copying permission.
from __future__ import annotations

from moat.mqtt.errors import MoatMQTTException

from .packet import PUBREL, MQTTFixedHeader, MQTTPacket, PacketIdVariableHeader


class PubrelPacket(MQTTPacket):  # noqa: D101
    VARIABLE_HEADER = PacketIdVariableHeader
    PAYLOAD = None

    @property
    def packet_id(self):  # noqa: D102
        return self.variable_header.packet_id

    @packet_id.setter
    def packet_id(self, val: int):
        self.variable_header.packet_id = val

    def __init__(
        self,
        fixed: MQTTFixedHeader = None,
        variable_header: PacketIdVariableHeader = None,
    ):
        if fixed is None:
            header = MQTTFixedHeader(PUBREL, 0x02)  # [MQTT-3.6.1-1]
        else:
            if fixed.packet_type != PUBREL:
                raise MoatMQTTException(
                    f"Invalid fixed packet type {fixed.packet_type} for PubrelPacket init",
                )
            header = fixed
        super().__init__(header)
        self.variable_header = variable_header
        self.payload = None

    @classmethod
    def build(cls, packet_id):  # noqa: D102
        variable_header = PacketIdVariableHeader(packet_id)
        return PubrelPacket(variable_header=variable_header)
