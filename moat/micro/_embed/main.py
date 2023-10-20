cfg = {}

import machine
from moat.micro.rtc import state
from moat.micro.compat import log

def set(attr, value=None, fs=None):
    if state is None and fs is False:
        raise RuntimeError("no RTC")
    if state is not None and not fs:
        state[attr] = state
    else:
        import os
        fn = f"moat.{attr}"
        try:
            f = open(fn, "r")
        except OSError:
            pass  # most likely file not found
        else:
            with f:
                d = f.read()
            if d == str(value):
                return
        with open(fn, "w") as f:
            f.write(str(value))

def get(attr, fs=None, default=None):
    if state is not None and fs is not True:
        if attr in state:
            return state[attr]
    if state is None or fs is not False:
        try:
            f = open(f"moat.{attr}", "r")
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
        state = get("state", default="skip")

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
        set("state", new_state)

    if state[0:4] == "skip":
        log(state)
        return

    # no empty path
    try:
        sys.path.remove("")
    except ValueError:
        pass
    # /lib to the front
    try:
        sys.path.remove("/lib")
    except ValueError:
        pass
    sys.path.insert(0, "/lib")

    fallback = False
    if state in ("fallback", "fbskip"):
        import sys

        sys.path.insert(0, "/fallback")
        fallback = True

    print("Start MoaT:", state, file=sys.stderr)
    from moat.micro.compat import print_exc
    from moat.micro.main import main

    cfg = "moat_fb.cfg" if fallback else "moat.cfg"
    try:
        main(cfg, fake_end=fake_end)

    except KeyboardInterrupt:
        print("MoaT stopped.", file=sys.stderr)

    except SystemExit:
        new_state = get("state")
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

        try:
            new_state = crash[state]
        except KeyError:
            new_state = state
        else:
            set("state", new_state)

        log("CRASH! REBOOT to %r", new_state, err=exc)
        time.sleep_ms(1000)
        machine.soft_reset()

    else:
        log("MoaT Ended.")
        sys.exit(0)


def g():
    go("once")


if __name__ == "__main__":
    go()
