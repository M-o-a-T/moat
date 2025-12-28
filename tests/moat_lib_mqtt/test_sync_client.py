from __future__ import annotations  # noqa: D100

import pytest
import sys

from moat.lib.mqtt import MQTTPublishPacket, QoS
from moat.lib.mqtt.sync_client import MQTTClient

pytestmark = [pytest.mark.network]


@pytest.mark.parametrize("qos", [QoS.AT_MOST_ONCE, QoS.AT_LEAST_ONCE, QoS.EXACTLY_ONCE])
def test_publish_subscribe(qos: QoS) -> None:  # noqa: D103
    with MQTTClient() as client, client.subscribe("test/+") as messages:
        client.publish("test/text", "test åäö", qos=qos)
        client.publish("test/binary", b"\x00\xff\x00\x1f", qos=qos)
        packets: list[MQTTPublishPacket] = []
        for packet in messages:
            packets.append(packet)
            if len(packets) == 2:
                break

        assert packets[0].topic == "test/text"
        assert packets[0].payload == "test åäö"
        assert packets[1].topic == "test/binary"
        assert packets[1].payload == b"\x00\xff\x00\x1f"


if sys.version_info < (3, 11):  # noqa: UP036

    class BaseExceptionGroup(BaseException):  # noqa: A001, D101
        exceptions: list[BaseExceptionGroup] = []


def test_retained_message() -> None:  # noqa: D103
    try:
        with MQTTClient() as client:
            if not client.cap_retain:
                pytest.skip("Retain not available")
            client.publish("retainedtest", "test åäö", retain=True)
            with client.subscribe("retainedtest") as messages:
                for packet in messages:
                    assert packet.topic == "retainedtest"
                    assert packet.payload == "test åäö"
                    break
    except BaseExceptionGroup as exc:
        while isinstance(exc, BaseExceptionGroup) and len(exc.exceptions) == 1:
            exc = exc.exceptions[0]
        raise exc  # noqa: TRY201
