# noqa:D104
# Copyright (c) 2015 Nicolas JOUANIN
#
# See the file license.txt for copying permission.
from __future__ import annotations

from moat.mqtt.errors import MoatMQTTException

from .connack import ConnackPacket
from .connect import ConnectPacket
from .disconnect import DisconnectPacket
from .packet import (
    CONNACK,
    CONNECT,
    DISCONNECT,
    PINGREQ,
    PINGRESP,
    PUBACK,
    PUBCOMP,
    PUBLISH,
    PUBREC,
    PUBREL,
    SUBACK,
    SUBSCRIBE,
    UNSUBACK,
    UNSUBSCRIBE,
    MQTTFixedHeader,
)
from .pingreq import PingReqPacket
from .pingresp import PingRespPacket
from .puback import PubackPacket
from .pubcomp import PubcompPacket
from .publish import PublishPacket
from .pubrec import PubrecPacket
from .pubrel import PubrelPacket
from .suback import SubackPacket
from .subscribe import SubscribePacket
from .unsuback import UnsubackPacket
from .unsubscribe import UnsubscribePacket

packet_dict = {
    CONNECT: ConnectPacket,
    CONNACK: ConnackPacket,
    PUBLISH: PublishPacket,
    PUBACK: PubackPacket,
    PUBREC: PubrecPacket,
    PUBREL: PubrelPacket,
    PUBCOMP: PubcompPacket,
    SUBSCRIBE: SubscribePacket,
    SUBACK: SubackPacket,
    UNSUBSCRIBE: UnsubscribePacket,
    UNSUBACK: UnsubackPacket,
    PINGREQ: PingReqPacket,
    PINGRESP: PingRespPacket,
    DISCONNECT: DisconnectPacket,
}


def packet_class(fixed_header: MQTTFixedHeader):  # noqa: D103
    try:
        cls = packet_dict[fixed_header.packet_type]
        return cls
    except KeyError:
        raise MoatMQTTException(  # pylint:disable=W0707 # noqa:B904
            f"Unexpected packet Type {fixed_header.packet_type!r}",
        )
