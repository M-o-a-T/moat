cfg = {}

import machine
import msgpack

##
# State:
# skip -- do nothing, go to prompt
# fallback -- use fallback. NO RECOVERY except with boot command
# fbskip -- use fallback. Skip if there's a crash
# fbonce -- use fallback, skip next
# test -- work normally now, always use fallback next time
# std -- work normally now, use fallback if there's a crash
# once -- work normally now, skip next
# main -- always work normally

def go_moat(state=None, fake_end=True, log=False):
    import uos, utime
    fallback=False

    uncond = {
            "test":"fallback",
            "fbonce":"fallback",
            "once":"skip",
            "skiponce":"std",
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

    if state in ("fallback","fbskip","fbonce"):
        import usys
        usys.path.insert(0,"/fallback")
        fallback = True

    print("Start MoaT:",state)
    from moat.compat import print_exc
    from moat.main import main

    cfg = "moat_fb.cfg" if fallback else "moat.cfg"
    try:
        main(state=state, fake_end=fake_end, log=log, cfg=cfg, fallback=fallback)

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

if __name__ == "__main__":
    go_moat(fake_end=False)

