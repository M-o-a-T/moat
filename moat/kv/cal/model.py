"""
Moat-KV client data model for calendars
"""

from __future__ import annotations


from moat.kv.obj import ClientEntry, ClientRoot, AttrClientEntry
from moat.kv.errors import ErrorRoot

import logging

logger = logging.getLogger(__name__)


class CalAlarm(AttrClientEntry):
    """
    An alarm handler. ``True`` is sent to @cmd. If @state doesn't follow
    within @timeout (default ten) seconds, raise an alarm and skip the
    delay. Otherwise go to the next entry.

    @src if set overrides the acknowledge source of the calendar.
    """

    ATTRS = ("cmd", "state", "delay", "src", "timeout")

    cls = ClientEntry


class CalEntry(AttrClientEntry):
    """
    A calendar entry to be monitored specifically (usually recurring).

    The entry's name is the UUID in the parent calendar.

    Summary+start+duration are updated from the calendar when it changes.
    @alarms, if set, modify when the entry's alarm sequence should trigger.
    @src if set overrides the acknowledge source of the calendar.
    """

    ATTRS = ("summary", "start", "duration", "alarms", "src")

    @classmethod
    def child_type(cls, name):
        if isinstance(name, int):
            return CalAlarm
        return ClientEntry


class CalBase(AttrClientEntry):
    """
    A monitored calendar. Every @freq seconds the CalDAV server at @url
    is queried for events during the next @days. They are published
    to @dst/UUID as records with summary/start/duration/alarmtime(s)/UID.

    @dst gets the same data, but for the next-most alarm time.
    @src is the signal that the alarm has been acknowledged.
    """

    ATTRS = ("url", "username", "password", "freq", "days", "dst", "src")

    @classmethod
    def child_type(cls, name):
        if isinstance(name, int):
            return CalAlarm
        return CalEntry


class CalRoot(ClientRoot):
    cls = {}
    reg = {}
    CFG = "cal"
    err = None

    async def run_starting(self):
        if self.err is None:
            self.err = await ErrorRoot.as_handler(self.client)
        await super().run_starting()

    @property
    def server(self):
        return self["server"]

    @classmethod
    def register(cls, typ):
        def acc(kls):
            cls.reg[typ] = kls
            return kls

        return acc

    @classmethod
    def child_type(kls, name):
        return CalBase
