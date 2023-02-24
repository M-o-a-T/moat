cfg = {}

import machine

from builtins import __import__ as _imp

def imp(name, drop=False):
    m,n = name.rsplit(".",1)
    try:
        m = "app."+m
        if drop:
            sys.modules.pop(m,None)
        m = _imp(m)
        # 'm' is the "app" module
        for a in name.split("."):
            m = getattr(m,a)
        return m
    except AttributeError:
        raise AttributeError(name)


async def gen_apps(cfg, tg, print_exc):
    apps = []
    for name,v in cfg.get("apps",{}).items():
        try:
            cmd = imp(v)
        except Exception as exc:
            print("Could not load",name,repr(exc))
            print_exc(exc)
            continue

        a = (name,cmd,cfg.get(name, {}))
        apps.append(a)
    return apps


def main(state=None, fake_end=True, log=False, fallback=False, cfg=cfg):
    import uos

    from .compat import TaskGroup, print_exc, sleep_ms
    from .base import StdBase

    if isinstance(cfg,str):
        import msgpack
        with open(cfg,"rb") as f:
            cfg = msgpack.unpackb(f.read())

    def cfg_setup(t, apps):
        # start apps
        for name,cmd,lcfg in apps:
            if cmd is None:
                continue
            try:
                cmd = cmd(t, name, lcfg, cfg)
            except TypeError:
                print(cmd,t,name,type(lcfg),type(cfg))
                raise
            setattr(t, "dis_"+name, cmd)

    def cfg_network(n):
        import network, time

        wlan = network.WLAN(network.STA_IF) # create station interface
        wlan.active(True)       # activate the interface
        if "addr" in n:
            wlan.ifconfig((n["addr"],n["netmask"],n["router"],n["dns"]))
        wlan.connect(n["ap"], n.get("pwd", '')) # connect to an AP

        n = 0
        if wlan.isconnected():
            return
        print("WLAN", end="")
        while not wlan.isconnected():
            if n > 300:
                print(" - no connection")
                raise RuntimeError("no network link")
            n += 1
            time.sleep(0.1)
            print(".", end="")
        print(" -", wlan.ifconfig()[0])

    if "net" in cfg:
        cfg_network(cfg["net"])

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

        # network
        async def run_network(port):
            from moat.micro.stacks.net import network_stack
            async def cb(t,b):
                t = t.stack(StdBase, fallback=fallback, state=state, cfg=cfg)
                cfg_setup(t, apps)
                try:
                    await b.run()
                except (EOFError, OSError):
                    await t.aclose()
            await network_stack(cb, port=port)

        # Console/serial
        async def run_console(force_write=False, **kw):
            from moat.micro.stacks import console_stack
            from moat.micro.proto.stream import AsyncStream
            import micropython
            micropython.kbd_intr(-1)
            t,b = console_stack(AsyncStream(sys.stdin.buffer, sys.stdout.buffer, force_write=force_write), **kw)
            t = t.stack(StdBase, fallback=fallback, state=state, cfg=cfg)
            cfg_setup(t, apps)
            return await tg.spawn(b.run)

        if sys.platform == "rp2":
            # use the console. USB, so no data loss; use msgpack's "illegal
            # data" byte for additional safety.
            await run_console(reliable=True, log=log, msg_prefix=0xc1)

        elif sys.platform == "linux":
            port = uos.getenv("MOATPORT")
            if port:
                await tg.spawn(run_network, int(port))
            else:
                await tg.spawn(reliable=True, log=log)

        elif sys.platform in ("esp32","esp8266"):
            port = cfg["link"]["port"]
            # Use networking. On Linux we can accept multiple parallel connections.
            await tg.spawn(run_network, port)

        else:
            raise RuntimeError("No idea what to do on %r!" % (sys.platform,))

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
            pass  # end of taskgroup

    from moat.micro.compat import run
    run(_main)

