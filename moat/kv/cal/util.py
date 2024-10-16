from __future__ import annotations

from datetime import datetime, timedelta, timezone, date, time
from dateutil.rrule import rrulestr
from vobject.icalendar import VAlarm

async def find_next_alarm(calendar, future=10, now = None, zone=timezone.utc) -> Tuple(VAlarm,datetime):
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
        end=datetime.now()+timedelta(days=future),
        event=True,
        expand=False,
    )

    if now is None:
        now = datetime.now(timezone.utc)
    print("here is some ical data:")
    ev = None
    ev_t = None

    for e in events_fetched:
        v = e.vobject_instance.vevent
        t_start = next_start(v, now)
        t_alarm = None
        for al in e.vobject_instance.vevent.components():
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
                ev, ev_t = e, t_al
    return ev,ev_t


def next_start(v, now):
    st = v.dtstart.value
    try:
        rule = rrulestr(v.rrule.value, dtstart=st)
    except AttributeError:
        pass
    else:
        excl = set()
        for edt in v.contents.get('exdate', ()):
            for ed in edt.value:
                excl.add(ed)

        st = rule.after(now, inc=True)
        while st in excl:
            st = rule.after(edt, inc=False)

        for edt in v.contents.get('rdate', ()):
            for ed in edt.value:
                if now <= ed.value < st:
                    st = ed.value

    return st


