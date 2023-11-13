"""
Datellite main code.
"""
from __future__ import annotations

from contextlib import suppress

import machine

# XXX m.m.compat and msgpack cannot be superseded
from moat.micro.compat import log

import msgpack as mp

cfg = {}

try:
    mem=machine.RTC().memory
except AttributeError:
    def mem(x=None):
        return b""

def set_rtc(attr, value=None, fs=None):
    "Setter for a value in RTC / file system"
    if not fs:
        try:
            s = mp.unpackb(mem())
        except ValueError:
            pass
        else:
            s[attr] = value
            mem(mp.packb(s))
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
            s = mp.unpackb(mem())
            return s[attr]
        except (ValueError, KeyError):
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


def go(state=None, fake_end=True):
    """
    Start MoaT.

    The interpreter state is read from Flash / RTC, and updated as appropriate.

    * skip
      Do nothing, exit to MicroPython prompt.

    * std
      Work normally. Enter Fallback mode if there's a problem.
      (Warning: Switching to fallback doesn't always work, esp. when you
      run out of memory or otherwise hard-crash the system. Always set up a
      hardware watchdog, if available.)

    * safe
      Work normally. Enter Fallback mode next time.

    * fallback
      Use the `moat_fb.cfg` config file and the `/fallback` library.

    * fbskip
      Use fallback mode once, then "skip".

    * once
      Work normally once, then "skip".

    * main
      Always work normally.
    """

    import sys
    import time

    if state is None:
        state = get_rtc("state", default="skip")

    uncond = {
        "once": "skip",
        "skiponce": "std",
        "safe": "fallback",
        "fbskip": "fallback",
    }
    crash = {
        "std": "fallback",
        "fbskip": "skip",
    }

    try:
        new_state = uncond[state]
    except KeyError:
        new_state = state
    else:
        set_rtc("state", new_state)

    if state[0:4] == "skip":
        log(state)
        return

    # no empty path
    with suppress(ValueError):
        sys.path.remove("")

    # /lib to the front
    with suppress(ValueError):
        sys.path.remove("/lib")
    sys.path.insert(0, "/lib")

    fallback = False
    if state in ("fallback", "fbskip"):
        sys.path.insert(0, "/fallback")
        fallback = True

    print("Start MoaT:", state, file=sys.stderr)
    from moat.micro.main import main

    cfg = "moat_fb.cfg" if fallback else "moat.cfg"
    try:
        main(cfg, fake_end=fake_end)

    except KeyboardInterrupt:
        print("MoaT stopped.", file=sys.stderr)

    except SystemExit:
        new_state = get_rtc("state")
        print("REBOOT to", new_state, file=sys.stderr)
        time.sleep_ms(100)
        machine.soft_reset()

    except BaseException as exc:
        if sys.platform == "linux":
            if isinstance(exc, EOFError):
                log("MoaT stopped: EOF")
                sys.exit(0)
            log("CRASH! Exiting!", err=exc)
            sys.exit(1)

        new_state = crash.get(state, state)
        set_rtc("state", new_state)

        log("CRASH! %r :: REBOOT to %r", exc, new_state, err=exc)
        time.sleep_ms(1000)
        machine.soft_reset()

    else:
        log("MoaT Ended.")
        sys.exit(0)


def g():
    "shortcut for ``go('once')``"
    go("once")


if __name__ == "__main__":
    go()
