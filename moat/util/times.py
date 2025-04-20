"""\
This code implements calculating an offset to an under-specified future
time. Like "how long until next Wednesday 8 am"?

The code also supports the inverse question, as in "how long until it's no
longer Wednesday 8 am something".
"""

from __future__ import annotations

import anyio
import datetime as dt
import time
from calendar import monthrange

from . import attrdict

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Awaitable

startup = dt.datetime.now().astimezone()
_log = None
TRACE = None


def now(force=False):  # noqa:ARG001 pylint: disable=unused-argument
    "current time"
    return dt.datetime.now().astimezone()


class t_iter:
    "an iterator that returns on well-defined time intervals"

    def __init__(self, interval):
        self.interval = interval

    def time(self):
        "get-time hook"
        return time.monotonic()

    async def sleep(self, dt):
        "sleep hook"
        await anyio.sleep(max(dt, 0))

    def __aiter__(self):
        self._t = self.time() - self.interval
        return self

    def __anext__(self) -> Awaitable[None]:
        t = self.time()
        dt = self._t - t
        if dt > 0:
            self._t += self.interval
        else:
            self._t = t + self.interval
            dt = 0
        return self.sleep(dt)


units = (
    (365 * 24 * 60 * 60, "yr"),
    (30 * 24 * 60 * 60, "mo"),
    (7 * 24 * 60 * 60, "wk"),
    (24 * 60 * 60, "dy"),
    (60 * 60, "hr"),
    (60, "min"),
)  # seconds are handled explicitly, below


def ts2iso(ts:float, delta=False, msec=1):
    """
    Convert a timestamp to a human-readable absolute-time string, optionally with delta.
    """
    res = dt.datetime.fromtimestamp(ts,dt.UTC).astimezone().isoformat(sep=" ", timespec="milliseconds")
    if delta:
        res += f" ({humandelta(ts-time.time(), ago=True, msec=msec)})"
    return res

def humandelta(delta: dt.timedelta, ago:bool=False, msec=1, segments=2) -> str:
    """
    Convert a timedelta into a human-readable string.

    Set @ago to report "in X / Y ago" instead of "+/- X".

    @msec specifies the number of digits on seconds. The default is 1. This
    number is reduced to zero if >1h, or one if >1min.

    @segments is the number of information blocks to print, as usually you
    don't need to know how many excess minutes a 2-week 3-day 5+hour time
    segment has. The default is 2. Pass 9 for "everything", zero for "one,
    but everything shorter than a minute is 'now'"
    """
    res = []
    res1 = ""
    res2 = ""
    if isinstance(delta, dt.timedelta):
        if delta.days < 0:
            assert delta.seconds >= 0
            # right now this code only handles positive seconds
            # timedelta(0,-1) => timedelta(-1,24*60*60-1)
            if ago:
                res2=" ago"
            else:
                res1 = "-"
            delta = -delta
        elif ago:
            res1="in "
        delta = delta.days + 24 * 60 * 60 + delta.seconds + delta.microseconds / 1e6
    elif delta < 0:
        delta = -delta
        if ago:
            res2 = " ago"
        else:
            res1 = "-"
    elif ago:
        res1 = "in "
    done = 0
    for lim, name in units:
        if delta > lim:
            res.append(f"{int(delta // lim)} {name}")
            delta %= lim
            if lim>100:
                msec=0
            elif msec>1:
                msec=1
            done += 1
            if done == segments:
                break
    if done < segments and delta >= 0.1**msec:
        if delta >= 1:
            res.append(f"{delta:.{msec}f} sec")
        elif delta > .001:
            res.append(f"{delta*1000:.{max(0,msec-3)}f} msec")
        else:
            res.append(f"{delta*1000000:.{max(0,msec-6)}f} µsec")

    if len(res) < 1:
        return "now"

    return res1 + " ".join(res) + res2


def unixtime(tm):
    """
    Returns the Unix timestamp of a datetime object.

    Deprecated: these days there's the `datetime.timestamp` method.
    """
    return tm.timestamp()


def isodate(yr, wk, wdy):
    """
    Return the date of the given year/week/weekday combination.
    """
    res = dt.date(yr, 1, 1)
    _, _, dy = res.isocalendar()
    return res + dt.timedelta(7 * (wk - 1) + wdy - dy)


def simple_time_delta(w):
    """
    Convert a string ("1 day 2 hours") to a timedelta.
    """
    w = w.split() if isinstance(w, str) else list(w)[:]
    s = 0
    m = 1
    while w:
        if len(w) == 1:
            pass
        elif w[1] in ("s", "sec", "second", "seconds"):
            w.pop(1)
        elif w[1] in ("m", "min", "minute", "minutes"):
            m = 60
            w.pop(1)
        elif w[1] in ("h", "hr", "hour", "hours"):
            m = 60 * 60
            w.pop(1)
        elif w[1] in ("d", "dy", "day", "days"):
            m = 60 * 60 * 24
            w.pop(1)
        elif w[1] in ("w", "wk", "week", "weeks"):
            m = 60 * 60 * 24 * 7
            w.pop(1)
        elif w[1] in ("m", "mo", "month", "months"):
            m = 60 * 60 * 24 * 30  # inexact!
            w.pop(1)
        elif w[1] in ("y", "yr", "year", "years"):
            m = 60 * 60 * 24 * 365  # inexact!
            w.pop(1)
        elif w[1] in ("+", "-"):
            pass
        else:
            raise SyntaxError("unknown unit", w[1])
        s += float(m) * float(w[0])
        w.pop(0)
        if w:
            if w[0] == "+":
                w.pop(0)
                m = 1
            elif w[0] == "-":
                w.pop(0)
                m = -1
            else:
                m = 1  # "1min 59sec"
    return s


def collect_words(cur, w, back:bool=False):
    """\
        Build a data structure representing time offset from a specific
        start.

        @cur: start time, may be None.
        @w: words describing the time offset.
        """
    p = attrdict()
    p.h = None
    p.m = None  # absolute hour/minute/second
    p.s = None

    p.yr = None
    p.mn = None  # absolute year/month/day
    p.dy = None

    p.wk = None
    p.dow = None  # week_of_year, weekday, which day?
    p.nth = None

    p.now = now().astimezone() if cur is None else cur

    weekdays = {
        "monday": 0,
        "tuesday": 1,
        "wednesday": 2,
        "thursday": 3,
        "friday": 4,
        "saturday": 5,
        "sunday": 6,
        "mon": 0,
        "tue": 1,
        "wed": 2,
        "thu": 3,
        "fri": 4,
        "sat": 5,
        "sun": 6,
        "mo": 0,
        "tu": 1,
        "we": 2,
        "th": 3,
        "fr": 4,
        "sa": 5,
        "su": 6,
    }
    f = None

    w = list(w)
    try:
        s = float(w[0])
    except (IndexError, ValueError, TypeError):
        pass
    else:
        if s > 1000000000:  # 30 years plus. Forget it, that's a unixtime.
            p.now = dt.datetime.fromtimestamp(s).astimezone()
            w.pop(0)

    while w:
        if w[0] == "+":
            w.pop(0)
            f = 1
        elif w[0] == "-":
            w.pop(0)
            f = -1

        # "monday" without a number simply is next monday.
        if isinstance(w[0], str) and w[0].lower() in weekdays:
            if p.dow is not None:
                raise SyntaxError("You already specified the day of week")
            if f is not None:
                raise SyntaxError("A sign makes no sense here")
            p.dow = weekdays[w[0].lower()]
            p.nth = 0
            w.pop(0)
            continue

        val = int(w.pop(0))
        if f is not None:
            val = f * val
            f = None

        unit = w.pop(0)
        if unit in ("s", "sec", "second", "seconds"):
            if p.s is not None:
                raise SyntaxError("You already specified the second")
            if not (-60 < val < 60):
                raise ValueError("Seconds need to be between 0 and 59")
            p.s = val

        elif unit in ("m", "min", "minute", "minutes"):
            if p.m is not None:
                raise SyntaxError("You already specified the minute")
            if not (-60 < val < 60):
                raise ValueError("Minutes need to be between 0 and 59")
            p.m = val

        elif unit in ("h", "hr", "hour", "hours"):
            if p.h is not None:
                raise SyntaxError("You already specified the hour")
            if not (-24 < val < 24):
                raise ValueError("Hours need to be between 0 and 23")
            p.h = val

        elif unit in ("d", "dy", "day", "days"):
            if p.dy is not None:
                raise SyntaxError("You already specified the day")
            if val == 0 or abs(val) > 31:
                raise ValueError("Months only have 31 days max")
            p.dy = val

        elif unit in ("m", "mo", "month", "months"):
            if p.mn is not None:
                raise SyntaxError("You already specified the month")
            if val == 0 or abs(val) > 12:
                raise ValueError("Years only have 12 months max")
            p.mn = val

        elif unit in ("y", "yr", "year", "years"):
            if p.yr is not None:
                raise SyntaxError("You already specified the year")
            if 0 < val < 100:
                val += p.now.year
            else:
                if ((val < p.now.year-100 or val > p.now.year) if back
                    else 
                    (val < p.now.year or val >= p.now.year + 100)):
                    raise ValueError(f"Year {val} would require a time machine.")
            p.yr = val

        elif unit in ("w", "wk", "week", "weeks"):
            if p.wk is not None:
                raise SyntaxError("You already specified the week-of-year")
            if val == 0 or abs(val) > 53:
                raise ValueError("Years only have 53 weeks max")
            p.wk = val

        elif unit in weekdays:
            # "2 monday" is the second Monday, i.e. day 8…14.
            if p.dow is not None:
                raise SyntaxError("You already specified the day of week")
            if val == 0 or abs(val) > 4:
                raise ValueError(
                    "Months have max. 5 of each weekday; use -1 if you want the last one.",
                )
            p.dow = weekdays[unit]
            p.nth = val
            continue
        else:
            raise SyntaxError("unknown unit", unit)
    return p


def time_until(args, t_now=None, invert=False, back=False):
    """\
        Find the next time which is in the future and matches the arguments.
        If "invert" is True, find the next time which does *not*.
        """
    p = collect_words(t_now, args, back=back)

    p.res = p.now

    s_one = -1 if back else 1

    # Theory of operation:
    # For each step, there are four cases:
    #
    # a- can be left alone
    #    = do nothing
    # b- needs to be increased
    #    = if at the limit, set to start value and increase the next position
    # c- needs to be at one specific value
    #    = if too large, increase the next position; then set.
    # d- (b) AND (c) both
    #    = accomplished by moving the intended value one step back
    #      during the crucial comparison
    # Another complication is that if somebody specifies a month but not
    # a day/hour/whatever, presumably they mean "as soon as that month
    # arrives" and not "that month, same day/hour/minute/second as now".

    def lim12():
        return 12

    def lim30():
        return monthrange(p.res.year, p.res.month)[1]

    def lim24():
        return 23

    def lim60():
        return 59

    def check_year(force=False):
        clear_fields = (
            {"second": 59, "minute": 59, "hour": 23, "day": 31, "month": 12}
            if back
            else {"second": 0, "minute": 0, "hour": 0, "day": 1, "month": 1}
        )
        # This is simpler, as there's nothing a year is owerflowing into.
        # (I do hope that this won't change any time soon …)
        if p.yr is None:
            if force:
                p.res = p.res.replace(year=p.res.year + s_one, **clear_fields)
        else:
            p.res = p.res.replace(year=p.yr, **clear_fields)

    def step(sn, ln, beg, lim, nextfn, clear_fields, cf2):  # shortname, longname, limit
        if back:
            clear_fields = cf2

        def next_whatever(force=False):
            goal = getattr(p, sn)
            real = getattr(p.res, ln)
            if goal is None:
                rgoal = real  # (a) and (b)
            elif goal < 0:
                rgoal = lim() + goal + 1
            else:
                rgoal = goal
            if force:
                rgoal += s_one  # (b) and (d)

            if (
                (real < rgoal or rgoal < beg) if back else (real > rgoal or rgoal > lim())
            ):  # needs increasing: (b), maybe (c)/(d)
                h = {ln: lim() if back else beg}
                h.update(clear_fields)
                p.res = p.res.replace(**h)
                nextfn(True)
                force = False
                if back:
                    if rgoal < beg:
                        rgoal = lim()
                else:
                    if rgoal > lim():
                        rgoal = beg
            if force or goal is not None:  # noqa:SIM102
                if real != rgoal:  # otherwise we clear fields for no reason
                    h = {ln: rgoal}
                    h.update(clear_fields)
                    try:
                        p.res = p.res.replace(**h)
                    except ValueError:
                        print(h)
                        raise
            # … and if the goal is None, this is either (a),
            # or 'our' value has been set to the beginning value, above

        return next_whatever

    check_month = step(
        "mn",
        "month",
        1,
        lim12,
        check_year,
        {"second": 0, "minute": 0, "hour": 0, "day": 1},
        {"second": 59, "minute": 59, "hour": 23, "day": 31},
    )
    check_day = step(
        "dy",
        "day",
        1,
        lim30,
        check_month,
        {"second": 0, "minute": 0, "hour": 0},
        {"second": 59, "minute": 59, "hour": 23},
    )
    check_hour = step(
        "h",
        "hour",
        0,
        lim24,
        check_day,
        {"second": 0, "minute": 0},
        {"second": 59, "minute": 59},
    )
    check_min = step("m", "minute", 0, lim60, check_hour, {"second": 0}, {"second": 59})
    check_sec = step("s", "second", 0, lim60, check_min, {}, {})

    def nth():
        if p.nth > 0:
            return 1 + ((p.res.day - 1) // 7)
        else:
            return -1 - ((lim30() - p.res.day) // 7)

    # Intermission: figure out how long until the condition is False
    if invert:
        p.delta = None

        def get_delta(fn, sn=None, ln=None):
            if p.delta is not None and p.delta == p.now:
                return
            if getattr(p, sn) is None:
                return
            if getattr(p.now, ln) != getattr(p, sn):
                p.delta = p.now
                return
            p.res = p.now
            fn(True)
            d = p.res
            if p.delta is None or s_one * p.delta.timestamp() > s_one * d.timestamp():
                p.delta = d

        get_delta(check_year, "yr", "year")
        get_delta(check_month, "mn", "month")
        get_delta(check_day, "dy", "day")
        if p.delta is not None and p.delta == p.now:
            return p.now

        get_delta(check_hour, "h", "hour")
        get_delta(check_min, "m", "minute")
        get_delta(check_sec, "s", "second")
        if p.delta is not None and p.delta == p.now:
            return p.now

        if p.wk is not None:  # week of the year
            _yr, wk, dow = p.now.isocalendar()
            if p.wk != wk:
                return p.now
            p.res = p.now
            check_day(True)
            if back:  # use x-if-y-else-z
                d = p.res - dt.timedelta(dow - 1)  # until end-of-week
            else:
                d = p.res + dt.timedelta(7 - dow)  # until end-of-week
            if p.delta is None or s_one * p.delta > s_one * d:
                p.delta = d
        if p.dow is not None:
            _yr, wk, dow = p.now.isocalendar()
            dow -= 1  # 1…7 ⇒ 0…6
            if p.dow != dow:
                return p.now
            p.res = p.now
            check_day(True)
            if p.delta is None or s_one * p.delta.timestamp() > s_one * p.res.timestamp():
                p.delta = p.res
        if p.nth:  # may be zero
            p.res = p.now
            if p.nth != nth():
                return p.now

        return p.delta

    # Now here's the fun part: figure out how long until the condition is true
    # first, check absolute values
    check_year(False)
    check_month(False)
    check_day(False)

    # Next: the weekday-related stuff. We assume, for convenience, that
    # any conflicting specifications simply mean "afterwards".

    # p.wk : week of the year (1…53)
    # p.dow : day of the week (Thursday)
    # p.nth : which day in the week (i.e. 1st Monday)
    def upd(delta):
        if not delta:
            return
        p.res = p.res + dt.timedelta(s_one * delta)
        if s_one * p.res.timestamp() > s_one * p.now.timestamp():
            if back:
                p.res = p.res.replace(hour=23, minute=59, second=59)
            else:
                p.res = p.res.replace(hour=0, minute=0, second=0)
        if s_one * p.res.timestamp() < s_one * p.now.timestamp():
            p.res = p.now

    if p.wk:  # week of the year
        _yr, wk, dow = p.res.isocalendar()
        if s_one * p.wk < s_one * wk:
            check_year(True)
            _yr, wk, dow = p.res.isocalendar()
            if back and _yr != p.res.year:
                _yr, wk, dow = p.res.replace(day=p.res.day - 7).isocalendar()
                wk += 1
        if p.wk != wk:
            upd(s_one * 7 * (p.wk - wk))

        if p.mn is None and p.dy is None:
            # No month/day specified, so assume that we can go back a bit.
            # (iso day 1 of week 1 of year X may be in December X-1.)
            # … but not into the past, please!
            if back:
                upd(dow - 7)
            else:
                upd(1 - dow)
            if s_one * p.res.timestamp() < s_one * p.now.timestamp():
                p.res = p.now

    if p.dow is not None:
        _yr, wk, dow = p.res.isocalendar()
        dow -= 1  # 1…7 ⇒ 0…6 (mon…sun)
        if back:
            if p.dow > dow:
                dow += 7  # prev week
            upd(dow - p.dow)
        else:
            if p.dow < dow:
                dow -= 7  # next week
            upd(p.dow - dow)

    if p.nth:  # may be zero or None
        if s_one * p.nth < s_one * nth():
            upd(7 * (4 + s_one * (p.nth - nth())))
            # That will take me to the first.
            if s_one * p.nth < s_one * nth():  # five weekdays in this month!
                upd(7)
                # … except when it doesn't.
        if s_one * p.nth > s_one * nth():
            upd(7 * s_one * (p.nth - nth()))
            # Either way, as if by magic, we now get the correct date.

    check_hour(False)
    check_min(False)
    check_sec(False)

    return p.res
