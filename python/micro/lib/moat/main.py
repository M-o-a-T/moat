cfg = {}

import machine

def main(state=None, fake_end=True, log=False, fallback=False):
    import uos

    if fallback:
        import usys
        usys.path.insert(0,"/fallback")

    from moat.compat import TaskGroup, print_exc
    from moat.base import StdBase

    from uasyncio import taskgroup as _tgm, sleep_ms

    _tgm.DEBUG=True
    del _tgm


    async def setup(tg, state=None):
        import sys

#       nonlocal no_exit

#       import msgpack
#       global cfg
#       try:
#           with open("moat.cfg") as f:
#               cfg.update(msgpack.unpack(f))
#       except OSError:
#           pass
#       else:
#           no_exit = cfg.get("console",{}).get("no_exit",no_exit)

        if sys.platform == "rp2":
            # use the console. USB, so no data loss.
            from moat.stacks import console_stack
            import micropython
            micropython.kbd_intr(-1)
            t,b = await console_stack(reliable=True, log=log, s2=sys.stdout.buffer, force_write=True, console=0xc1)
            t = t.stack(StdBase, fallback=fallback, state=state)
            return await tg.spawn(b.run)

        if sys.plaform == "linux":
            mp = uos.getenv("MOATPORT")
            if mp:
                mp = int(mp)
                # Use networking. On Linux we can accept multiple parallel connections.
                async def run():
                    from moat.stacks import network_stack_iter
                    async with TaskGroup() as tg:
                        async for t,b in network_stack_iter(multiple=True, port=mp):
                            t = t.stack(StdBase, fallback=fallback, state=state)
                            return await tg.spawn(b.run)
                return await tg.spawn(run)

            else:
                # Console test
                from moat.stacks import console_stack
                import micropython
                micropython.kbd_intr(-1)
                t,b = console_stack(reliable=True, log=log)
                t = t.stack(StdBase, fallback=fallback, state=state)
                return await tg.spawn(b.run)

        raise RuntimeError("Which system does this run on?")

    async def _main(state=None):
        import sys

        async with TaskGroup() as tg:
            await tg.spawn(setup,tg, state)

            # start whatever else needs adding here

            # if started from the command line, fake being done
            await sleep_ms(1500)
            if fake_end:
                sys.stdout.write("OK\x04\x04>")


    from moat.compat import run
    run(_main, state)

