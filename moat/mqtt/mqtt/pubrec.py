# Copyright (c) 2015 Nicolas JOUANIN
#
# See the file license.txt for copying permission.
from __future__ import annotations
from moat.mqtt.errors import MoatMQTTException
from .packet import PUBREC, MQTTFixedHeader, MQTTPacket, PacketIdVariableHeader


class PubrecPacket(MQTTPacket):
    VARIABLE_HEADER = PacketIdVariableHeader
    PAYLOAD = None

    @property
    def packet_id(self):
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
            header = MQTTFixedHeader(PUBREC, 0x00)
        else:
            if fixed.packet_type != PUBREC:
                raise MoatMQTTException(
                    "Invalid fixed packet type %s for PubrecPacket init" % fixed.packet_type,
                )
            header = fixed
        super().__init__(header)
        self.variable_header = variable_header
        self.payload = None

    @classmethod
    def build(cls, packet_id: int):
        v_header = PacketIdVariableHeader(packet_id)
        packet = PubrecPacket(variable_header=v_header)
        return packet
