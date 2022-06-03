cfg = {}

def go_moat(no_exit=False):

    async def setup(evt):
        import sys
        import micropython
        from moat.compat import spawn
        from uasyncio.stream import Stream
        from moat.cmd import Handler,Reliable,Request,Base
        nonlocal no_exit

        import msgpack
        global cfg
        try:
            with open("moat.cfg") as f:
                cfg.update(msgpack.unpack(f))
        except OSError:
            pass
        else:
            no_exit = cfg.get("console",{}).get("no_exit",no_exit)

        h = None

        ## Runtime for RPy2: use the console
        try:
            import rp2
        except Exception:
            pass
        else:
            micropython.kbd_intr(-1)
            h = Handler(Stream(sys.stdin.buffer), None if no_exit else evt)
            t = h.stack(Reliable)

        ## TODO on an ESP32, use a TCP connection or an MQTT channel or …

        if h is None:
            evt.set()
            raise RuntimeError("Which system does this run on?")

        t = t.stack(Request)
        t = t.stack(Base)
        spawn(h.run)
        return t


    async def main():
        from moat.compat import Event
        evt = Event
        cmd = await setup(evt)

        await evt.wait()

    from moat.compat import run
    run(main)
