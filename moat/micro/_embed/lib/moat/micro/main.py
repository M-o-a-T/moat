"""
Main entry point for satellites.

Called from the root "main.py".
"""

from __future__ import annotations

import os
import sys

import machine

import moat.micro.console as cons
from moat.util import attrdict, merge, to_attrdict
from moat.lib.codec.moat_cbor import Codec as CBOR
from moat.lib.micro import AC_use, L, TaskGroup, sleep_ms
from moat.lib.rpc import MsgSender

WDT = None


def wr_exc(exc):
    "write exception and backtrace to stderr, and maybe flash"
    if "moat.err" not in os.listdir():
        with open("moat.err", "w") as f:
            print("Error:", repr(exc), file=f)
            sys.print_exception(exc, f)

    print("Error:", repr(exc), file=sys.stderr)
    sys.print_exception(exc, sys.stderr)


def main(cfg: str | dict, i: attrdict, fake_end=False) -> None:
    """
    The MoaT.micro satellite's main entry point.

    Args:
        cfg: the configuration. If this is a string, it's the name of the
             config file, with the data stored in CBOR.

        fake_end: if set, sends a fake MicroPython prompt to trick the setup code into
                  thinking that the current command has concluded. This way
                  it can cleanly terminate the setup phase and start the
                  local dispatcher.
    """
    if isinstance(cfg, str):
        with open(cfg, "rb") as f:
            cfg = CBOR().decode(f.read())
    if type(cfg) is dict:
        cfg = to_attrdict(cfg)

    if "rtc" in cfg:
        from moat.micro.rtc import RTC  # noqa:PLC0415

        RTC.init(cfg["rtc"])

    # Update config from RTC memory, if present
    if not i["fb"]:
        try:
            rcfg = RTC.get_sync("cfg")
        except KeyError:
            pass
        else:
            merge(cfg, rcfg)

    # Start the hardware watchdog timer early
    for v in cfg.values():
        if v.get("app", "") != "wdt.Cmd":
            continue
        if v.get("running", True) and v.get("hw", False):
            machine.WDT(v.get("id", 0), v.get("t", 5000))
        break

    def cfg_network(n):
        import time  # noqa: PLC0415

        import network  # noqa: PLC0415

        network.hostname(n["name"])
        if "country" in n:
            network.country(n["country"])
        if "ap" in n:
            wlan = network.WLAN(network.STA_IF)  # create station interface
            wlan.active(True)
            if "addr" in n:
                nm = n.get("netmask", 24)
                if isinstance(nm, int):
                    ff = (1 << 32) - 1
                    nm = (ff << (32 - nm)) & ff
                    nm = f"{(nm >> 24) & 0xFF}.{(nm >> 16) & 0xFF}.{(nm >> 8) & 0xFF}.{nm & 0xFF}"
                wlan.ifconfig((n["addr"], n["netmask"], n["router"], n["dns"]))
            wlan.connect(n["ap"], n.get("pwd", ""))  # connect to an AP
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
            time.sleep_ms(100)
            print(".", end="", file=sys.stderr)
        print(" -", wlan.ifconfig()[0], file=sys.stderr)

    if "net" in cfg and cfg["net"].get("name", None) is not None:
        cfg_network(cfg["net"])

    async def _main():
        import sys  # noqa: PLC0415

        from moat.lib.rpc import RootCmd  # noqa: PLC0415

        cons.main = m = cons.Main(wr_exc)
        dsp = await AC_use(m, RootCmd(cfg, i=i))
        m.tg = await AC_use(m, TaskGroup())
        m.root = MsgSender(dsp)

        m.main_task = await m.tg.spawn(dsp.task)
        if L:
            await dsp.wait_ready()
        else:
            await sleep_ms(1000)
        if fake_end:
            sys.stdout.write("OK\x04\x04>")
        else:
            print("MoaT is up.", file=sys.stderr)

        try:
            await m.wait()
        except BaseException as exc:
            await m.die_(exc)
            print("MoaT has terminated.", file=sys.stderr)
        else:
            if m.console is None:
                print("MoaT is down.", file=sys.stderr)
            else:
                print("MoaT is in the background.", file=sys.stderr)

    from asyncio import create_task, run_until_complete  # noqa: PLC0415

    task = create_task(_main())
    run_until_complete(task)
