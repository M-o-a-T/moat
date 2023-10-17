# global hardware watchdog
WDT = None

import os
import sys
import machine

import msgpack

from moat.util import NotGiven
from moat.micro.compat import print_exc


def dict_upd(d,k,v):
    if isinstance(v,dict):
        dd = d.setdefault(k,{})
        for kk,vv in v.items():
            dict_upd(dd,kk,vv)
        if not dd:
            del d[k]
    elif v is NotGiven:
        d.pop(k,None)
    else:
        d[k] = v

def main(cfg:str|dict, fake_end=False):
    """
    The MoaT.micro satellite's main entry point.

    If @cfg is a string, it's the name of the config file.

    @fake_end sends a fake MicroPython prompt to trick the setup code into
    thinking that the current command has concluded, so it can cleanly
    terminate / start the local dispatcher.
    """
    if isinstance(cfg, str):
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

        if "name" in n:
            network.hostname(n["name"])
        if "country" in n:
            network.country(n["country"])
        if "ap" in n:
            wlan = network.WLAN(network.STA_IF)  # create station interface
            wlan.active(True)
            if "addr" in n:
                nm = n.get("netmask",24)
                if isinstance(nm,int):
                    ff = (1<<32) - 1
                    nm = (ff << (32-nm)) & ff
                    nm = f"{(nm>>24)&0xFF}.{(nm>>16)&0xFF}.{(nm>>8)&0xFF}.{nm&0xFF}"
                wlan.ifconfig((n["addr"], n["netmask"], n["router"], n["dns"]))
            wlan.connect(n["ap"], n.get("pwd", ''))  # connect to an AP
        else:
            wlan = network.WLAN(network.AP_IF)  # create a station interface

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
        from moat.micro.compat import idle

        async with Dispatch(cfg) as dsp:
            if fake_end:
                from .compat import sleep_ms
                await sleep_ms(1000)
                sys.stdout.write("OK\x04\x04>")
                await sleep_ms(100)

            await dsp.task()
            await idle()

    from moat.micro.compat import run
    run(_main)
