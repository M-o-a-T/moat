# Copyright (c) 2015 Nicolas JOUANIN
#
# See the file license.txt for copying permission.
from __future__ import annotations
from datetime import datetime

import anyio

from moat.mqtt.codecs import int_to_bytes_str
from moat.mqtt.mqtt.packet import PUBLISH

DOLLAR_SYS_ROOT = "$SYS/broker/"
STAT_BYTES_SENT = "bytes_sent"
STAT_BYTES_RECEIVED = "bytes_received"
STAT_MSG_SENT = "messages_sent"
STAT_MSG_RECEIVED = "messages_received"
STAT_PUBLISH_SENT = "publish_sent"
STAT_PUBLISH_RECEIVED = "publish_received"
STAT_START_TIME = "start_time"
STAT_CLIENTS_MAXIMUM = "clients_maximum"
STAT_CLIENTS_CONNECTED = "clients_connected"
STAT_CLIENTS_DISCONNECTED = "clients_disconnected"


class BrokerSysPlugin:
    def __init__(self, context):
        self.context = context
        # Broker statistics initialization
        self._stats = dict()
        self.sys_handle = None

    def _clear_stats(self):
        """
        Initializes broker statistics data structures
        """
        for stat in (
            STAT_BYTES_RECEIVED,
            STAT_BYTES_SENT,
            STAT_MSG_RECEIVED,
            STAT_MSG_SENT,
            STAT_CLIENTS_MAXIMUM,
            STAT_CLIENTS_CONNECTED,
            STAT_CLIENTS_DISCONNECTED,
            STAT_PUBLISH_RECEIVED,
            STAT_PUBLISH_SENT,
        ):
            self._stats[stat] = 0

    async def _broadcast_sys_topic(self, topic_basename, data):
        return await self.context.broadcast_message(topic_basename, data)

    async def on_broker_pre_start(self, *args, **kwargs):  # pylint: disable=unused-argument
        self._clear_stats()

    async def on_broker_post_start(self, *args, **kwargs):  # pylint: disable=unused-argument
        self._stats[STAT_START_TIME] = datetime.now()
        from moat.mqtt.version import get_version

        version = "MoaT-MQTT version " + get_version()
        await self.context.broadcast_message(
            DOLLAR_SYS_ROOT + "version",
            version.encode(),
            retain=True,
        )

        # Start $SYS topics management
        try:
            sys_interval = int(self.context.config.get("sys_interval", 0))
            if sys_interval > 0:
                self.context.logger.debug(
                    "Setup $SYS broadcasting every %d secondes",
                    sys_interval,
                )
                evt = anyio.Event()
                self.context._broker_instance._tg.start_soon(
                    self.broadcast_dollar_sys_topics_loop,
                    sys_interval,
                    evt,
                )
                await evt.wait()
            else:
                self.context.logger.debug("$SYS disabled")
        except KeyError:
            pass
            # 'sys_internal' config parameter not found

    async def on_broker_pre_stop(self, *args, **kwargs):  # pylint: disable=unused-argument
        # Stop $SYS topics broadcasting
        if self.sys_handle:
            await self.sys_handle.cancel()

    async def broadcast_dollar_sys_topics_loop(self, interval, evt):
        with anyio.CancelScope() as scope:
            self.sys_handle = scope
            await evt.set()
            while True:
                await anyio.sleep(interval)
                await self.broadcast_dollar_sys_topics()

    async def broadcast_dollar_sys_topics(self):
        """
        Broadcast dynamic $SYS topics updates and reschedule next execution depending on 'sys_interval' config
        parameter.
        """

        # Update stats
        uptime = datetime.now() - self._stats[STAT_START_TIME]
        client_connected = self._stats[STAT_CLIENTS_CONNECTED]
        client_disconnected = self._stats[STAT_CLIENTS_DISCONNECTED]
        inflight_in = 0
        inflight_out = 0
        messages_stored = 0
        for session in self.context.sessions:
            inflight_in += session.inflight_in_count
            inflight_out += session.inflight_out_count
            messages_stored += session.retained_messages_count
        messages_stored += len(self.context.retained_messages)
        subscriptions_count = 0
        for topic in self.context.subscriptions:
            subscriptions_count += len(self.context.subscriptions[topic])

        # Broadcast updates
        await self._broadcast_sys_topic(
            "load/bytes/received",
            int_to_bytes_str(self._stats[STAT_BYTES_RECEIVED]),
        )
        await self._broadcast_sys_topic(
            "load/bytes/sent",
            int_to_bytes_str(self._stats[STAT_BYTES_SENT]),
        )
        await self._broadcast_sys_topic(
            "messages/received",
            int_to_bytes_str(self._stats[STAT_MSG_RECEIVED]),
        )
        await self._broadcast_sys_topic(
            "messages/sent",
            int_to_bytes_str(self._stats[STAT_MSG_SENT]),
        )
        await self._broadcast_sys_topic("time", str(datetime.now()).encode("utf-8"))
        await self._broadcast_sys_topic("uptime", int_to_bytes_str(int(uptime.total_seconds())))
        await self._broadcast_sys_topic("uptime/formated", str(uptime).encode("utf-8"))
        await self._broadcast_sys_topic("clients/connected", int_to_bytes_str(client_connected))
        await self._broadcast_sys_topic(
            "clients/disconnected",
            int_to_bytes_str(client_disconnected),
        )
        await self._broadcast_sys_topic(
            "clients/maximum",
            int_to_bytes_str(self._stats[STAT_CLIENTS_MAXIMUM]),
        )
        await self._broadcast_sys_topic(
            "clients/total",
            int_to_bytes_str(client_connected + client_disconnected),
        )
        await self._broadcast_sys_topic(
            "messages/inflight",
            int_to_bytes_str(inflight_in + inflight_out),
        )
        await self._broadcast_sys_topic("messages/inflight/in", int_to_bytes_str(inflight_in))
        await self._broadcast_sys_topic("messages/inflight/out", int_to_bytes_str(inflight_out))
        await self._broadcast_sys_topic(
            "messages/inflight/stored",
            int_to_bytes_str(messages_stored),
        )
        await self._broadcast_sys_topic(
            "messages/publish/received",
            int_to_bytes_str(self._stats[STAT_PUBLISH_RECEIVED]),
        )
        await self._broadcast_sys_topic(
            "messages/publish/sent",
            int_to_bytes_str(self._stats[STAT_PUBLISH_SENT]),
        )
        await self._broadcast_sys_topic(
            "messages/retained/count",
            int_to_bytes_str(len(self.context.retained_messages)),
        )
        await self._broadcast_sys_topic(
            "messages/subscriptions/count",
            int_to_bytes_str(subscriptions_count),
        )

    async def on_mqtt_packet_received(self, *args, **kwargs):  # pylint: disable=unused-argument
        packet = kwargs.get("packet")
        if packet:
            packet_size = packet.bytes_length
            self._stats[STAT_BYTES_RECEIVED] += packet_size
            self._stats[STAT_MSG_RECEIVED] += 1
            if packet.fixed_header.packet_type == PUBLISH:
                self._stats[STAT_PUBLISH_RECEIVED] += 1

    async def on_mqtt_packet_sent(self, *args, **kwargs):  # pylint: disable=unused-argument
        packet = kwargs.get("packet")
        if packet:
            packet_size = packet.bytes_length
            self._stats[STAT_BYTES_SENT] += packet_size
            self._stats[STAT_MSG_SENT] += 1
            if packet.fixed_header.packet_type == PUBLISH:
                self._stats[STAT_PUBLISH_SENT] += 1

    async def on_broker_client_connected(self, *args, **kwargs):  # pylint: disable=unused-argument
        self._stats[STAT_CLIENTS_CONNECTED] += 1
        self._stats[STAT_CLIENTS_MAXIMUM] = max(
            self._stats[STAT_CLIENTS_MAXIMUM],
            self._stats[STAT_CLIENTS_CONNECTED],
        )

    async def on_broker_client_disconnected(self, *args, **kwargs):  # pylint: disable=unused-argument
        self._stats[STAT_CLIENTS_CONNECTED] -= 1
        self._stats[STAT_CLIENTS_DISCONNECTED] += 1
