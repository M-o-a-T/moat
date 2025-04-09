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
from moat.util.compat import log
from moat.rtc import get_rtc, set_rtc

cfg = {}


def go(state=None, cmd=True):
    """
    Start MoaT.

    The system state can be passed as an argument; otherwise it's read from
    RTC, Flash, or defaults to "skip".

    If @cmd is True, the system has been started manually. This prevents
    processing of error tracebacks. Also, a fake "OK" prompt is emitted, to
    fool the host's command line processing.

    @state can be one of these strings:

    * skip
      Do nothing, exit to MicroPython prompt.

    * std
      Work normally. Enter Fallback mode if there's a problem.
      (Warning: Switching to fallback doesn't always work, esp. when you
      run out of memory or otherwise hard-crash the system. Always set up a
      hardware watchdog, if available.)

    * safe
      Work normally. Unconditionally enter "fallback" mode next time.

    * saferom
      Work normally. Unconditionally enter "rom" mode next time.

    * fallback
      Use the `moat_fb.cfg` config file and the `/fallback` library.

    * fbskip
      Use "fallback" mode once, then "skip".

    * fbrom
      Use "fallback" mode once, then "rom".

    * rom
      Use the `moat_rom.cfg` config file and the library in Flash.

    * romskip
      Use "rom" mode once, then "skip".

    * once
      Work normally once, then "skip".

    * main
      Always work normally.
    """

    import sys
    import time

    if state is None:
        state = get_rtc("state")
    if state is None:
        try:
            os.stat("moat_fb.cfg")
        except OSError:
            pass
        else:
            state = "fallback"
    if state is None:
        try:
            os.stat("moat_rom.cfg")
        except OSError:
            pass
        else:
            state = "rom"
    if state is None:
        state = "skip"

    uncond = {
        "once": "skip",
        "skiponce": "std",
        "safe": "fallback",
        "saferom": "rom",
        "fbskip": "fallback",
        "fbrom": "rom",
        "romskip": "rom",
    }
    crash = {
        "std": "fallback",
        "fbskip": "skip",
        "romskip": "skip",
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
    with suppress(ValueError):
        sys.path.remove("/")
    with suppress(ValueError):
        sys.path.remove(".")

    # we do keep the root in the path, but at the end
    sys.path.append("/")

    # /lib to the front

    fallback = None
    if state in ("fallback", "fbskip"):
        sys.path.insert(0, "/fallback")
        fallback = "_fb"
    elif state in ("rom", "romskip"):
        with suppress(ValueError):
            sys.path.remove(".frozen")
        sys.path.insert(0, ".frozen")
        fallback = "_rom"
    else:
        fallback = ""
        with suppress(ValueError):
            sys.path.remove("/lib")
        sys.path.insert(0, "/lib")

    print(f"Start MoaT{fallback}:", state, file=sys.stderr)
    from moat.micro.main import main

    cfg = f"moat{fallback}.cfg"
    i = attrdict(fb=fallback, s=state, ns=new_state, fm=_fm, fa=_fa)

    if cmd:
        main(cfg, i=i, fake_end=True)
        return

    try:
        main(cfg, i=i)

    except KeyboardInterrupt:
        print("MoaT stopped.", file=sys.stderr)

    except SystemExit:
        new_state = get_rtc("state")
        print("REBOOT to", new_state, file=sys.stderr)
        time.sleep_ms(100)
        machine.soft_reset()

    except BaseException as exc:
        del main
        sys.modules.clear()

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
