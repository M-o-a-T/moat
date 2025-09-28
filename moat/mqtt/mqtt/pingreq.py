# Copyright (c) 2015 Nicolas JOUANIN  # noqa: D100
#
# See the file license.txt for copying permission.
from __future__ import annotations

from moat.mqtt.errors import MoatMQTTException

from .packet import PINGREQ, MQTTFixedHeader, MQTTPacket


class PingReqPacket(MQTTPacket):  # noqa: D101
    VARIABLE_HEADER = None
    PAYLOAD = None

    def __init__(self, fixed: MQTTFixedHeader = None):
        if fixed is None:
            header = MQTTFixedHeader(PINGREQ, 0x00)
        else:
            if fixed.packet_type != PINGREQ:
                raise MoatMQTTException(
                    f"Invalid fixed packet type {fixed.packet_type} for PingReqPacket init",
                )
            header = fixed
        super().__init__(header)
        self.variable_header = None
        self.payload = None
