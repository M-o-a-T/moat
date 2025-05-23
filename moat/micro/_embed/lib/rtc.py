"""
RTC support for main
"""

from __future__ import annotations

import machine
import sys

cfg = {}

try:
    mem = machine.RTC().memory
except AttributeError:

    def mem(x=None):  # noqa:D103,ARG001
        return b""


def set_rtc(attr, value=None, fs=None):
    "Setter for a value in RTC / file system"
    if not fs:
        try:
            s = eval(mem().split(b'\0')[0].decode("utf-8"))
        except Exception as exc:
            if mem() != b"":
                print("Memory decode problem:",mem(),repr(exc), file=sys.stderr)
            s = {}
        if s.get(attr,None) == value:
            return
        if value is Ellipsis:
            if attr in s:
                del s[attr]
        else:
            s[attr] = value
        mem(repr(s).encode("utf-8")+b'\0')
        return
    if fs is False:
        raise ValueError("no RTC")
    fn = f"moat.{attr}"
    try:
        f = open(fn)  # noqa:SIM115
    except OSError:
        pass  # most likely file not found
    else:
        with f:
            d = f.read()
        if d == str(value):
            return
    with open(fn, "w") as f:
        f.write(str(value))


def get_rtc(attr, fs=None, default=None):
    "Getter for a value in RTC / file system"
    if not fs:
        try:
            s = eval(mem().split(b'\0')[0].decode("utf-8"))
            return s[attr]
        except Exception:
            pass
    if fs is not False:
        try:
            f = open(f"moat.{attr}")  # noqa:SIM115
        except OSError:
            pass
        else:
            with f:
                res = f.read()
            return str(res)
    return default


def all_rtc():
    "Iterate RTC update values"
    try:
        s = eval(mem().split(b'\0')[0].decode("utf-8"))
        for k, v in s.items():
            if isinstance(v, dict):
                yield k, v
    except (ValueError, KeyError, OutOfData):
        pass
