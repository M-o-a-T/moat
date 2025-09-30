cfg = {}

import machine

from builtins import __import__ as _imp


def imp(name):
    m, n = name.rsplit(".", 1)
    try:
        m = _imp(m)
        for a in name.split(".")[1:]:
            m = getattr(m, a)
        return m
    except AttributeError:
        raise AttributeError(name)


async def gen_apps(cfg, tg, print_exc):
    apps = []
    for name, v in cfg.get("apps", {}).items():
        try:
            cmd = imp(v)
        except Exception as exc:
            print("Could not load", name, repr(exc))
            print_exc(exc)
            continue

        a = (name, cmd, cfg.get(name, {}))
        apps.append(a)
    return apps


def main(state=None, fake_end=True, log=False, fallback=False, cfg=cfg):
    import uos

    from moat.compat import TaskGroup, print_exc, sleep_ms
    from moat.base import StdBase

    if isinstance(cfg, str):
        import msgpack

        with open(cfg, "rb") as f:
            cfg = msgpack.unpackb(f.read())

    def cfg_setup(t, apps):
        # start apps
        for name, cmd, lcfg in apps:
            if cmd is None:
                continue
            try:
                cmd = cmd(t, name, lcfg, cfg)
            except TypeError:
                print(cmd, t, name, type(lcfg), type(cfg))
                raise
            setattr(t, "dis_" + name, cmd)

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
            t, b = await console_stack(
                reliable=True,
                log=log,
                s2=sys.stdout.buffer,
                force_write=True,
                console=0xC1,
            )
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
                        async for t, b in network_stack_iter(multiple=True, port=mp):
                            t = t.stack(StdBase, fallback=fallback, state=state, cfg=cfg)
                            cfg_setup(t, apps)
                            return await tg.spawn(b.run)

                return await tg.spawn(run)

            else:
                # Console test
                from moat.stacks import console_stack
                import micropython

                micropython.kbd_intr(-1)
                t, b = console_stack(reliable=True, log=log)
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
            await tg.spawn(setup, tg, state, apps)

            # If started from the ("raw") REPL, fake being done
            if fake_end:
                await sleep_ms(1000)
                sys.stdout.write("OK\x04\x04>")

    from moat.compat import run

    run(_main)
