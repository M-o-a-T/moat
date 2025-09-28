"""
RTC support for main
"""

from __future__ import annotations

import sys

import machine

cfg = {}

try:
    mem = machine.RTC().memory
except AttributeError:

    def mem(x=None):  # noqa:D103,ARG001
        return b""


def at(*a, **kw):
    """
    Setter for debugging.

    Usage: call ``at("something", or_other=42)`` at various places in your
    code. After a crash the data from the last such call will be available
    by calling ``get_rtc("debug")``.
    """
    set_rtc("debug", (a, kw), fs=False)


def set_rtc(attr, value=None, fs=None):
    "Setter for a value in RTC / file system"
    if not fs:
        try:
            s = eval(mem().split(b"\0")[0].decode("utf-8"))
        except Exception as exc:
            if mem() != b"":
                print("Memory decode problem:", mem(), repr(exc), file=sys.stderr)
            s = {}
        if s.get(attr) == value:
            return
        if value is Ellipsis:
            if attr in s:
                del s[attr]
        else:
            s[attr] = value
        mem(repr(s).encode("utf-8") + b"\0")
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
            s = eval(mem().split(b"\0")[0].decode("utf-8"))
            return s[attr]
        except Exception:  # noqa:S110
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
        s = eval(mem().split(b"\0")[0].decode("utf-8"))
    except (ValueError, KeyError, EOFError, SyntaxError):
        print("RTC: failed to eval", repr(mem()), file=sys.stderr)
    else:
        for k, v in s.items():
            if isinstance(v, dict):
                yield k, v
