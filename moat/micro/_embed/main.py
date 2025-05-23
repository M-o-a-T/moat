"""
Datellite main code.
"""
# ruff: noqa:E402

from __future__ import annotations

import gc as _gc

_gc.collect()
_fm = _gc.mem_free()
_fa = _gc.mem_alloc()

def go(state=None, cmd=True):
    """
    Start MoaT.

    The system state can be passed as an argument; otherwise it's read from
    RTC, Flash, or defaults to "skip".

    If @cmd is True, the system has been started manually. This prevents
    processing of error tracebacks. Also, a fake "OK" prompt is emitted, to
    fool the host's command line processing.

    The state can be a comma-separated list: the next state in the list
    will be used on reboot.

    * skip
      Do nothing: exit to MicroPython prompt.

    * std
      Work normally, i.e. load from /lib, /rom/lib, .frozen.
      mode if there's a problem. (Warning: Switching to fallback doesn't
      always work, esp. when you run out of memory or otherwise hard-crash
      the system. Always set up a hardware watchdog, if available.)

    * rom
      As above, but don't use /lib. Uses "moat_rom.cfg" if available.

    * flash
      Only use .frozen. Uses "moat_fb.cfg" if available.

    * norom
      Uses /lib and .frozen. Uses "moat_nr.cfg" if available.

    The default is "fallback" if moat_fb.cfg exists, else "rom" if
    moat_rom.cfg exists, else whatever is in "moat.cfg" ('mode' key)
    """

    from rtc import get_rtc, set_rtc
    import time
    import machine

    # copy from moat.util.compat
    import sys as sys
    def log(s, *x, err=None):
        if x:
            s = s % x
        print(s, file=sys.stderr)
        if err is not None:
            sys.print_exception(err, sys.stderr)

    states = [
            ("flash","moat_fb.cfg"),
            ("rom","moat_rom.cfg"),
            ("std","moat.cfg"),
    ]
    if state is None:
        state = get_rtc("state")
    if state is None:
        for st,fn in states:
            try:
                os.stat(fn)
            except OSError:
                pass
            else:
                state=st
                break
    if state is None:
        state = "skip"

    try:
        state,new_state = state.split(",",1)
    except ValueError
        new_state = state

    _set_rtc("state", new_state)
    if state == "skip":
        log(state)
        return

    fn = dict(states).get(state,"moat.cfg")

    # no empty path
    for p in ("","/",".","/lib",".frozen","/rom","/rom/lib"):
        try:
            sys.path.remove("")
        except ValueError:
            pass

    # build path
    if state in ("norom","std"):
        sys.path.append("/lib")
    if state in ("rom","std"):
        sys.path.append("/rom")
    if state in ("flash","rom","norom","std"):
        sys.path.append(".frozen")
    # keep the root in the path, but at the end
    sys.path.append("/")

    print("Start MoaT:", state, file=sys.stderr)

    from moat.micro.main import main

    cfg = f"moat{fallback}.cfg"
    i = dict(fb=fallback, s=state, ns=new_state, fm=_fm, fa=_fa)

    if cmd:
        main(cfg, i=i, fake_end=True)
        return

    try:
        main(cfg, i=i)

    except KeyboardInterrupt:
        print("MoaT stopped.", file=sys.stderr)

    except SystemExit:
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
