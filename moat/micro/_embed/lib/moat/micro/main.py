cfg = {}

import sys
from builtins import __import__ as _imp

import machine

# global hardware watchdog
WDT = None

def main(state=None, fake_end=True, log=False, fallback=False, cfg=cfg):
    import uos

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

    if "net" in cfg:
        cfg_network(cfg["net"])

    async def setup(tg, state, ready=None):
        import sys

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
                lossy=cfg["link"]["lossy"],
                log=log,
                msg_prefix=0xC1 if cfg["link"]["guarded"] else None,
                use_console=cfg["link"].get("console", False),
            )
            t = t.stack(StdBase, fallback=fallback, state=state, cfg=cfg)
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
            # Use networking.
            await tg.spawn(run_network, port, _name="run_port")

        else:
            raise RuntimeError("No idea what to do on %r!" % (sys.platform,))

    async def _main():
        import sys

        ready = Event()

        # config: load apps

        async with TaskGroup() as tg:
            # start comms (and load app frontends)
            await tg.spawn(setup, tg, state, _name="setup", ready=ready)

            # If started from the ("raw") REPL, fake being done
            if fake_end:
                await sleep_ms(1000)
                sys.stdout.write("OK\x04\x04>")
                await sleep_ms(100)

            ready.set()

            pass  # end of taskgroup

    from moat.micro.compat import run

    run(_main)
