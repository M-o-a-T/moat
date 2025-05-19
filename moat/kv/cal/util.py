from __future__ import annotations

from datetime import datetime, timedelta, date, time, UTC
from dateutil.rrule import rrulestr
from vobject.icalendar import VAlarm, VEvent

import logging

logger = logging.getLogger(__name__)


async def find_next_alarm(calendar, future=10, now=None, zone=UTC) -> Tuple(
    VAlarm,
    datetime,
):
    """
    fetch the next alarm in the current calendar

    returns an (event, alarm_time) tuple
    """
    ## It should theoretically be possible to find both the events and
    ## tasks in one calendar query, but not all server implementations
    ## supports it, hence either event, todo or journal should be set
    ## to True when searching.  Here is a date search for events, with
    ## expand:
    events_fetched = await calendar.search(
        start=datetime.now(),
        end=datetime.now() + timedelta(days=future),
        event=True,
        expand=False,
    )

    if now is None:
        now = datetime.now(UTC)
    ev = None
    ev_v = None
    ev_t = None

    for e in events_fetched:
        vx = None
        vx_t = None
        rids = set()
        # create a list of superseded events
        for v in e.vobject_instance.components():
            if v.behavior is not VEvent:
                continue
            try:
                rid = v.recurrence_id
            except AttributeError:
                continue
            else:
                rids.add(rid.value)

        # find earliest event, skipping superseded ones
        for v in e.vobject_instance.components():
            if v.behavior is not VEvent:
                continue
            try:
                rid = v.recurrence_id
            except AttributeError:
                rid = None

            t_start = next_start(v, now)
            if t_start is None:
                raise ValueError("Start time: ??")
                # t_start = next_start(v, now)
            if not t_start.tzinfo:
                t_start = t_start.astimezone(zone)
            if rid is None and t_start in rids:
                continue

            if vx is None or t_start < vx_t:
                vx, vx_t = v, t_start

        for al in vx.components():
            if al.behavior is not VAlarm:
                continue
            if not al.useBegin:
                continue
            if isinstance(t_start, date) and not isinstance(t_start, datetime):
                t_start = datetime.combine(t_start, time(0), tzinfo=zone)
                # XXX TODO count back from the current timezone's midnight

            t_al = t_start + al.trigger.value
            if t_al < now:
                continue
            if ev is None or ev_t > t_al:
                ev, ev_v, ev_t = e, vx, t_al
    if ev:
        logger.warning("Next alarm: %s at %s", ev.vobject_instance.vevent.summary.value, ev_t)
    return ev, ev_v, ev_t


def next_start(v, now, zone=UTC):
    st = v.dtstart.value
    if isinstance(st,date):
        st=datetime.combine(st,time(0,0,0)).astimezone(zone)
    try:
        rule = rrulestr(v.rrule.value, dtstart=st)
    except AttributeError:
        pass
    else:
        excl = set()
        for edt in v.contents.get("exdate", ()):
            for ed in edt.value:
                excl.add(ed)

        st = rule.after(now, inc=True)
        while st in excl:
            st = rule.after(edt, inc=False)

        for edt in v.contents.get("rdate", ()):
            for ed in edt.value:
                if now <= ed.value < st:
                    st = ed.value

    return st
