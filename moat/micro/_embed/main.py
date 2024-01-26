"""
Datellite main code.
"""
# ruff: noqa:E402

from __future__ import annotations

import gc as _gc

_gc.collect()
_fm = _gc.mem_free()
_fa = _gc.mem_alloc()

from contextlib import suppress

import machine

from moat.util import attrdict

# XXX m.m.compat and msgpack cannot be superseded
from moat.micro.compat import log
from moat.rtc import get_rtc, set_rtc

cfg = {}


def go(state=None, fake_end=True, cmd=True):
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

    x = " " * 1000
    print("Start MoaT:", state, file=sys.stderr)
    from moat.micro.main import main

    cfg = "moat_fb.cfg" if fallback else "moat.cfg"
    i = attrdict(fb=fallback, s=state, ns=new_state, fm=_fm, fa=_fa)

    if cmd:
        main(cfg, i=i, fake_end=fake_end)
        return

    try:
        main(cfg, i=i, fake_end=fake_end)

    except KeyboardInterrupt:
        print("MoaT stopped.", file=sys.stderr)

    except SystemExit:
        new_state = get_rtc("state")
        print("REBOOT to", new_state, file=sys.stderr)
        time.sleep_ms(100)
        machine.soft_reset()

    except BaseException as exc:
        del x
        if sys.platform == "linux":
            if isinstance(exc, EOFError):
                log("MoaT stopped: EOF")
                sys.exit(0)
            log("CRASH! Exiting!", err=exc)
            sys.exit(1)

        new_state = crash.get(state, new_state)
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
    go(cmd=False)
