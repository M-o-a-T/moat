cfg = {}

import machine

def go_moat(state=None, fake_end=True, log=False):
    """
    Start MoaT.

    The interpreter state is read from Flash and updated as appropriate.

    * skip
      Do nothing, exit to MicroPython prompt.
    
    * std
      Work normally. Enter Fallback mode if there's a problem.
      (Warning: Switching to fallback doesn't always work, esp. when you
      run out of memory or otherwise hard-crash the system.)

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

    import uos, utime, usys
    fallback=False

    uncond = {
            "once":"skip",
            "skiponce":"std",
            "safe":"fallback",
            "skipfb":"fallback",
    }
    crash = {
            "std":"fallback",
            "fbskip":"skip",
    }

    if state is None:
        try:
            f=open("moat.state","r")
        except OSError:
            print("No 'moat.state' found")
            return
        else:
            state=f.read()
            f.close()

    try:
        new_state = uncond[state]
    except KeyError:
        new_state = state
    else:
        f=open("moat.state","w")
        f.write(new_state)
        f.close()

    if state[0:4] == "skip":
        print(state)
        return

    # no empty path
    try:
        usys.path.remove("")
    except ValueError:
        pass
    # /lib to the front
    try:
        usys.path.remove("/lib")
    except ValueError:
        pass
    usys.path.insert(0,"/lib")

    if state in ("fallback","fbskip"):
        import usys
        usys.path.insert(0,"/fallback")
        fallback = True

    print("Start MoaT:",state)
    from moat.micro.compat import print_exc
    from moat.micro.main import main

    cfg = "moat_fb.cfg" if fallback else "moat.cfg"
    try:
        main(state=state, fake_end=fake_end, log=log, cfg=cfg, fallback=fallback)

    except KeyboardInterrupt:
        print("MoaT stopped.")

    except SystemExit:
        f=open("moat.state","r")
        new_state = f.read()
        f.close()
        print("REBOOT to", new_state)
        utime.sleep_ms(100)
        machine.soft_reset()

    except BaseException as exc:
        try:
            new_state = crash[state]
        except KeyError:
            new_state = state
        else:
            f=open("moat.state","w")
            f.write(new_state)
            f.close()

        print("CRASH! REBOOT to", new_state)
        print_exc(exc)
        utime.sleep_ms(500)
        machine.soft_reset()
    else:
        print("MoaT Ended.")

def g():
    go_moat("once")

if __name__ == "__main__":
    go_moat(fake_end=False)

