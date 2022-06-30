cfg = {}

import machine

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

    uncond = {
            "test":"fallback",
            "fbonce":"fallback",
            "once":"skip",
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
    if state=="skip":
        print("Skip.")
        return
    if state in ("fallback","fbskip","fbonce"):
        import usys
        usys.path.insert(0,"/fallback")
    if state in uncond:
        f=open("moat.state","w")
        f.write(uncond[state])
        f.close()

    print("Start MoaT:",state)
    from moat.compat import print_exc
    from moat.main import main

    try:
        main(state=state, fake_end=fake_end, log=log)
    except Exception as exc:
        if state in crash:
            f=open("moat.state","w")
            f.write(crash[state])
            f.close()
        print_exc(exc)
        utime.sleep_ms(500)
        machine.soft_reset()
    else:
        print("MoaT Ended.")

if __name__ == "__main__":
    go_moat(fake_end=False)

