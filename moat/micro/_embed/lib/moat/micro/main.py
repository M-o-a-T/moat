cfg = {}

import sys
from builtins import __import__ as _imp

import machine


def import_app(name, drop=False):
    m, n = name.rsplit(".", 1)
    a = None
    m = "app." + m
    if drop:
        sys.modules.pop(m, None)
    m = _imp(m)
    # 'm' is the "app" module
    for a in name.split("."):
        m = getattr(m, a)
    return m


def gen_apps(cfg, tg, print_exc):
    apps = []
    for name, v in cfg.get("apps", {}).items():
        try:
            cmd = import_app(v)
        except Exception as exc:
            print("Could not load", name, repr(exc), file=sys.stderr)
            print_exc(exc)
            continue

        a = (name, cmd, cfg.get(name, {}))
        apps.append(a)
    return apps


try:
    WDT = machine.WDT
except AttributeError:  # Unix
    # TODO: fork a background process
    class WDT:
        def __init__(self, timeout):
            self.t = timeout

        def feed(self):
            pass


_wdt = None
_wdt_chk = None


def wdt(t=None):
    """
    Fetch or set the WDT.

    _wdt_chk is set if the last access was a read.
    """
    global _wdt, _wdt_idle
    if t:
        if _wdt is not None:
            raise RuntimeError("WDT exists")
        _wdt = WDT(t * 1000)
        _wdt_chk = False
    elif _wdt is None:
        raise RuntimeError("No WDT")
    else:
        _wdt_chk = True
    return _wdt


def main(state=None, fake_end=True, log=False, fallback=False, cfg=cfg):
    import uos

    global _wdt

    from .base import StdBase
    from .compat import Event, TaskGroup, print_exc, sleep_ms

    if isinstance(cfg, str):
        import msgpack

        try:
            f = open(cfg, "rb")
        except OSError as err:
            raise OSError(cfg)
        with f:
            cfg = msgpack.unpackb(f.read())

    def cfg_setup(t, apps):
        # start apps
        for name, cmd, lcfg in apps:
            if cmd is None:
                continue
            try:
                cmd = cmd(t, name, lcfg, cfg)
            except TypeError:
                print(cmd, t, name, type(lcfg), type(cfg), file=sys.stderr)
                raise
            setattr(t, "dis_" + name, cmd)

    def cfg_network(n):
        import time

        import network

        wlan = network.WLAN(network.STA_IF)  # create station interface
        wlan.active(True)  # activate the interface
        if "addr" in n:
            wlan.ifconfig((n["addr"], n["netmask"], n["router"], n["dns"]))
        wlan.connect(n["ap"], n.get("pwd", ''))  # connect to an AP

        n = 0
        if wlan.isconnected():
            return
        print("WLAN", end="", file=sys.stderr)
        while not wlan.isconnected():
            if n > 300:
                print(" - no connection", file=sys.stderr)
                raise RuntimeError("no network link")
            n += 1
            time.sleep(0.1)
            print(".", end="", file=sys.stderr)
        print(" -", wlan.ifconfig()[0], file=sys.stderr)

    _wdt = None
    wdt_t = 0
    wdt_s = 0
    if "wdt" in cfg:
        wdt_t = cfg["wdt"].get("t", 10) * 1000
        if wdt_t:
            wdt_s = cfg["wdt"].get("s", 0)
            if wdt_s == 1:
                _wdt = WDT(timeout=wdt_t * 1.5)

    if "net" in cfg:
        cfg_network(cfg["net"])

    if wdt_s == 2:
        _wdt = WDT(timeout=wdt_t * 1.5)
    elif _wdt:
        _wdt.feed()

    async def setup(tg, state, apps, ready=None):
        import sys

        global _wdt
        # nonlocal no_exit

        # import msgpack
        # global cfg
        # try:
        # with open("moat.cfg") as f:
        # cfg.update(msgpack.unpack(f))
        # except OSError:
        # pass
        # else:
        # no_exit = cfg.get("console",{}).get("no_exit",no_exit)

        # network
        async def run_network(port):
            from moat.micro.stacks.net import network_stack

            async def cb(t, b):
                t = t.stack(StdBase, fallback=fallback, state=state, cfg=cfg)
                cfg_setup(t, apps)
                try:
                    await b.run()
                except (EOFError, OSError):
                    await t.aclose()

            await network_stack(cb, port=port)

        # Console/serial
        async def run_console(force_write=False):
            import micropython

            from moat.micro.stacks.console import console_stack

            micropython.kbd_intr(-1)
            try:
                in_b = sys.stdin.buffer
                out_b = sys.stdout.buffer
                from moat.micro.proto.stream import AsyncStream

                s = AsyncStream(in_b, out_b, force_write=force_write)
            except AttributeError:  # on Unix
                from moat.micro.proto.fd import AsyncFD

                s = AsyncFD(sys.stdin, sys.stdout)
            t, b = await console_stack(
                s,
                ready=ready,
                lossy=cfg["port"]["lossy"],
                log=log,
                msg_prefix=0xC1 if cfg["port"]["guarded"] else None,
            )
            t = t.stack(StdBase, fallback=fallback, state=state, cfg=cfg)
            cfg_setup(t, apps)
            await tg.spawn(b.run, _name="runcons")

        if sys.platform == "rp2":
            # uses the USB console -- XXX slightly buggy.
            await run_console(force_write=True)

        elif sys.platform == "linux":
            port = uos.getenv("MOATPORT")
            if port:
                await tg.spawn(run_network, int(port), _name="run_net")
            else:
                await run_console()

        elif sys.platform in ("esp32", "esp8266"):
            port = cfg["link"]["port"]
            # Use networking. On Linux we can accept multiple parallel connections.
            await tg.spawn(run_network, port, _name="run_port")

        else:
            raise RuntimeError("No idea what to do on %r!" % (sys.platform,))

        if wdt_s == 3:
            _wdt = WDT(timeout=wdt_t * 1.5)
        elif _wdt:
            _wdt.feed()

    async def _main():
        import sys

        global _wdt
        ready = Event()

        # config: load apps

        async with TaskGroup() as tg:
            apps = gen_apps(cfg, tg, print_exc)

            # start comms (and load app frontends)
            await tg.spawn(setup, tg, state, apps, _name="apps", ready=ready)

            # If started from the ("raw") REPL, fake being done
            if fake_end:
                await sleep_ms(1000)
                sys.stdout.write("OK\x04\x04>")
                await sleep_ms(100)

            if wdt_s == 4:
                _wdt = WDT(timeout=wdt_t * 1.5)

            ready.set()

            if _wdt is not None and wdt_t:
                n = cfg["wdt"].get("n", 1 + 60000 // wdt_t if wdt_t < 20000 else 3)
                if n:
                    wdt_chk = False
                    while not wdt_chk:
                        _wdt.feed()
                        await sleep_ms(wdt_t)
                        if n > 0:
                            n -= 1
                            if n == 0:
                                break

            pass  # end of taskgroup

    from moat.micro.compat import run

    run(_main)
