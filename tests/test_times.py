"""
Tests to figure out how long until a time spec fits / does not fit,
also stringification
"""

# ruff:noqa:D103 pylint: disable=missing-function-docstring,global-statement
from __future__ import annotations

import datetime

from moat.util.times import time_until

lnp = None
err = 0
now = None

# ruff:noqa:PLW0603 # update global var


def chk(iso, a, invert=False, back=False):
    a = () if a == "" else a.split(" ")
    res = time_until(a, t_now=now, invert=invert, back=back)
    if res is None and iso == "-":
        return
    res -= datetime.timedelta(0, 0, res.microsecond)
    res = str(res.replace(tzinfo=None))
    if iso == res:
        return

    global err
    global lnp
    if lnp is None or lnp != now:
        lnp = now
        print("@", now, "::")
    err += 1
    print("?", iso, "≠", res, "@", a, "I" if invert else "", "B" if back else "")


def test_fore():
    global now
    now = datetime.datetime(2003, 4, 5, 6, 7, 8).astimezone()

    chk("2003-04-05 06:07:08", "6 h 4 month 8 sec")
    chk("2003-04-05 06:07:10", "10 sec")
    chk("2003-04-05 06:08:02", "2 sec")
    chk("2003-04-05 06:07:50", "- 10 sec")
    chk("2003-04-05 06:11:02", "11 min 2 sec")
    chk("2003-04-05 11:00:50", "11 h - 10 sec")
    chk("2003-04-05 23:05:50", "- 1 h 5 min - 10 sec")

    chk("2003-12-29 00:00:00", "1 wk")
    chk("2004-01-01 00:00:12", "1 wk thu 12 sec")
    chk("2004-01-05 00:00:00", "2 wk")

    chk("2003-04-05 11:00:50", "11 h - 10 sec")
    chk("2003-04-05 11:45:50", "11 h - 15 min - 10 sec")
    chk("2003-04-05 06:07:08", "14 wk")
    chk("2003-04-07 00:00:00", "15 wk")
    chk("2004-03-22 00:00:00", "13 wk")

    #       April                  May
    # Su Mo Tu We Th Fr Sa  Su Mo Tu We Th Fr Sa
    #       1  2  3  4  5               1  2  3
    # 6  7  8  9 10 11 12   4  5  6  7  8  9 10
    # 13 14 15 16 17 18 19  11 12 13 14 15 16 17
    # 20 21 22 23 24 25 26  18 19 20 21 22 23 24
    # 27 28 29 30           25 26 27 28 29 30 31

    chk("2003-04-05 06:07:08", "sat")
    chk("2003-04-06 00:00:00", "sun")
    chk("2003-04-08 00:00:00", "tue")
    chk("2003-04-07 00:00:00", "mon")

    chk("2003-04-05 06:07:08", "1 sat")
    chk("2003-04-08 00:00:00", "2 tue")
    chk("2003-04-16 00:00:00", "3 wed")
    chk("2003-04-16 00:00:00", "-3 wed")
    chk("2003-04-24 00:00:00", "-1 thu")
    chk("2003-05-01 00:00:00", "1 thu")
    chk("2003-05-07 00:00:00", "1 wed")

    chk("-", "", True)
    chk("2003-04-05 06:07:09", "8 sec", True)
    chk("2003-04-05 06:07:08", "9 sec", True)
    chk("2003-04-05 06:07:09", "7 min 8 sec", True)
    chk("2003-04-05 06:07:08", "7 min 0 sec", True)

    chk("2003-04-07 00:00:00", "14 wk", True)
    chk("2003-04-05 06:07:08", "14 wk mon", True)
    chk("2003-04-06 00:00:00", "14 wk sat", True)
    chk("2003-04-05 06:07:08", "15 wk", True)

    assert not err


def test_back():
    global now
    now = datetime.datetime(2003, 4, 5, 6, 7, 8).astimezone()

    chk("2003-04-05 06:07:08", "6 h 4 month 8 sec", back=True)
    chk("2003-04-05 06:07:05", "5 sec", back=True)
    chk("2003-04-05 06:06:10", "10 sec", back=True)
    chk("2003-04-05 06:06:50", "- 10 sec", back=True)
    chk("2003-04-05 06:03:02", "3 min 2 sec", back=True)
    chk("2003-04-05 05:59:50", "05 h - 10 sec", back=True)
    chk("2003-04-04 23:05:50", "- 1 h 5 min - 10 sec", back=True)

    chk("2003-01-05 23:59:59", "1 wk", back=True)
    chk("2003-01-02 23:59:12", "1 wk thu 12 sec", back=True)
    chk("2002-12-31 23:59:12", "1 wk tue 12 sec", back=True)
    chk("2003-01-12 23:59:59", "2 wk", back=True)

    chk("2003-04-05 03:59:50", "03 h - 10 sec", back=True)
    chk("2003-04-05 03:45:50", "03 h - 15 min - 10 sec", back=True)
    chk("2003-03-30 23:59:59", "13 wk", back=True)
    chk("2003-04-05 06:07:08", "14 wk", back=True)
    chk("2002-04-14 23:59:59", "15 wk", back=True)

    chk("2003-04-05 06:07:08", "sat", back=True)
    chk("2003-03-30 23:59:59", "sun", back=True)
    chk("2003-04-01 23:59:59", "tue", back=True)
    chk("2003-03-31 23:59:59", "mon", back=True)

    chk("2003-04-05 06:07:08", "1 sat", back=True)
    chk("2003-03-11 23:59:59", "2 tue", back=True)
    chk("2003-03-19 23:59:59", "3 wed", back=True)
    chk("2003-03-12 23:59:59", "-3 wed", back=True)
    chk("2003-03-27 23:59:59", "-1 thu", back=True)
    chk("2003-03-31 23:59:59", "-1 mon", back=True)
    chk("2003-04-03 23:59:59", "1 thu", back=True)
    chk("2003-03-02 23:59:59", "1 sun", back=True)

    chk("2003-04-05 06:07:07", "8 sec", True, back=True)
    chk("2003-04-05 06:07:08", "7 sec", True, back=True)
    chk("2003-04-05 06:07:07", "7 min 8 sec", True, back=True)
    chk("2003-04-05 06:07:08", "7 min 20 sec", True, back=True)

    chk("2003-03-30 23:59:59", "14 wk", True, back=True)
    chk("2003-04-04 23:59:59", "14 wk sat", True, back=True)
    chk("2003-04-05 06:07:08", "14 wk mon", True, back=True)
    chk("2003-04-05 06:07:08", "15 wk", True, back=True)

    assert not err
