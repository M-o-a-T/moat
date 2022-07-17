cfg = {}

import machine

from builtins import __import__ as _imp


def imp(name):
    m,n = name.rsplit(".",1)
    try:
        m = _imp(m)
        for a in name.split(".")[1:]:
            m = getattr(m,a)
        return m
    except AttributeError:
        raise AttributeError(name)


async def gen_apps(cfg, tg, print_exc):
    apps = []
    for name,v in cfg.get("apps",{}).items():
        try:
            cmd = v["cmd"]
        except KeyError:
            cmd = None
        else:
            try:
                cmd = imp(cmd)
            except Exception as exc:
                print("Could not load",cmd,repr(exc))
                print_exc(exc)
                continue
        try:
            app = v["app"]
        except KeyError:
            app = None
        else:
            try:
                app = imp(app)(v.get("cfg",{}), cfg)
            except Exception as exc:
                print("Could not start",name,app,repr(exc))
                print_exc(exc)
                continue
            await tg.spawn(app.run)

        a = (name,app,cmd,v.get("cfg", {}))
        apps.append(a)
    return apps


def main(state=None, fake_end=True, log=False, fallback=False, cfg=cfg):
    import uos

    from moat.compat import TaskGroup, print_exc
    from moat.base import StdBase

    from uasyncio import taskgroup as _tgm, sleep_ms

    _tgm.DEBUG=True
    del _tgm


    def cfg_setup(t, apps):
        # start apps
        for name,app,cmd,lcfg in apps:
            if cmd is None:
                continue
            cmd = cmd(t, app if app is not None else lcfg, name)
            setattr(t, "dis_"+name, cmd)


    async def setup(tg, state, apps):
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
            t = t.stack(StdBase, fallback=fallback, state=state, cfg=cfg)
            cfg_setup(t, apps)
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
                            t = t.stack(StdBase, fallback=fallback, state=state, cfg=cfg)
                            cfg_setup(t, apps)
                            return await tg.spawn(b.run)
                return await tg.spawn(run)

            else:
                # Console test
                from moat.stacks import console_stack
                import micropython
                micropython.kbd_intr(-1)
                t,b = console_stack(reliable=True, log=log)
                t = t.stack(StdBase, fallback=fallback, state=state, cfg=cfg)
                cfg_setup(t, apps)
                return await tg.spawn(b.run)

        raise RuntimeError("Which system does this run on?")

    async def _main():
        import sys

        # config: load apps

        async with TaskGroup() as tg:
            apps = await gen_apps(cfg, tg, print_exc)

            # start comms (and load app frontends)
            await tg.spawn(setup,tg, state, apps)

            # If started from the ("raw") REPL, fake being done
            if fake_end:
                await sleep_ms(1000)
                sys.stdout.write("OK\x04\x04>")

    from moat.compat import run
    run(_main)

