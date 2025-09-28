# Copyright (c) 2015 Nicolas JOUANIN  # noqa: D100
#
# See the file license.txt for copying permission.
from __future__ import annotations

from functools import partial


class EventLoggerPlugin:  # noqa: D101
    def __init__(self, context):
        self.context = context

    async def log_event(self, *args, **kwargs):  # pylint: disable=unused-argument  # noqa: ARG002, D102
        self.context.logger.info(
            "### '%s' EVENT FIRED ###",
            kwargs["event_name"].replace("old", ""),
        )

    def __getattr__(self, name):
        if name.startswith("on_"):
            return partial(self.log_event, event_name=name)


class PacketLoggerPlugin:  # noqa: D101
    def __init__(self, context):
        self.context = context

    async def on_mqtt_packet_received(self, *args, **kwargs):  # pylint: disable=unused-argument  # noqa: ARG002, D102
        packet = kwargs.get("packet")
        session = kwargs.get("session")
        if session:
            self.context.logger.debug("%s <-in-- %r", session.client_id, packet)
        else:
            self.context.logger.debug("<-in-- %r", packet)

    async def on_mqtt_packet_sent(self, *args, **kwargs):  # pylint: disable=unused-argument  # noqa: ARG002, D102
        packet = kwargs.get("packet")
        session = kwargs.get("session")
        if session:
            self.context.logger.debug("%s -out-> %r", session.client_id, packet)
        else:
            self.context.logger.debug("-out-> %r", packet)
