cfg = {}

import sys
from builtins import __import__ as _imp
from moat.micro.compat import idle

import machine

# global hardware watchdog
WDT = None

def dict_upd(d,k,v):
    if isinstance(v,dict):
        dd = d.setdefault(k,{})
        for kk,vv in v.items():
            _upd(dd,kk,vv)
        if not dd:
            del d[k]
    elif v is NotGiven:
        d.pop(k,None)
    else:
        d[k] = v

def main(state=None, fake_end=True, log=False, fallback=False, cfg=cfg):
    import os

    from ..util import import_
    from .compat import Event, TaskGroup, print_exc, sleep_ms

    if isinstance(cfg, str):
        import msgpack

        try:
            f = open(cfg, "rb")
        except OSError as err:
            raise OSError(cfg)
        with f:
            cfg = msgpack.unpackb(f.read())

    # Update config from RTC memory, if present
    try:
        rtc = machine.RTC()
    except AttributeError:
        pass
    else:
        try:
            if (m := rtc.memory()) != b"":

                cf2 = msgpack.unpackb(m)
                for k,v in cf2:
                    if not isinstance(v,dict):
                        continue
                    dict_upd(cfg,k,v)

        except Exception as exc:
            print_exc(exc)

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


    async def _main():
        import sys
        from moat.micro.cmd.tree import Dispatch

        async with Dispatch(cfg) as dsp:
            if fake_end:
                await sleep_ms(1000)
                sys.stdout.write("OK\x04\x04>")
                await sleep_ms(100)

            await dsp.task()
            await idle()

    from moat.micro.compat import run
    run(_main)
