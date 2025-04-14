"""
RTC support for main
"""

from __future__ import annotations

import machine

from moat.lib.codec.cbor import Codec as _cbor
from moat.util import OutOfData

cfg = {}
_codec = _cbor()

try:
    mem = machine.RTC().memory
except AttributeError:

    def mem(x=None):  # noqa:D103,ARG001
        return b""


def set_rtc(attr, value=None, fs=None):
    "Setter for a value in RTC / file system"
    if not fs:
        try:
            s = _codec.decode(mem())
        except OutOfData:
            s = {}
        else:
            s[attr] = value
            mem(_codec.encode(s))
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
            s = _codec.decode(mem())
            return s[attr]
        except (OutOfData, KeyError):
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
        s = _codec.decode(mem())
        for k, v in s.items():
            if isinstance(v, dict):
                yield k, v
    except (ValueError, KeyError, OutOfData):
        pass
