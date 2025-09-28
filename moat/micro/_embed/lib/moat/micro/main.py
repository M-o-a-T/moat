"""
Main entry point for satellites.

Called from the root "main.py".
"""

from __future__ import annotations

import sys

from rtc import all_rtc

import machine

from moat.util import merge
from moat.lib.codec.cbor import Codec as CBOR
from moat.util.compat import L, TaskGroup, at, sleep_ms

from typing import TYPE_CHECKING  # isort:skip

if TYPE_CHECKING:
    from moat.util import attrdict

WDT = None


def main(cfg: str | dict, i: attrdict, fake_end=False):
    """
    The MoaT.micro satellite's main entry point.

    If @cfg is a string, it's the name of the config file.

    @fake_end sends a fake MicroPython prompt to trick the setup code into
    thinking that the current command has concluded, so it can cleanly
    terminate / start the local dispatcher.
    """
    at("M1")
    if isinstance(cfg, str):
        try:
            f = open(cfg, "rb")  # noqa:SIM115
        except OSError:
            raise OSError(cfg) from None
        with f:
            cfg = CBOR().decode(f.read())

    # Update config from RTC memory, if present
    at("M2")
    if not i["fb"]:
        for k, v in all_rtc():
            merge(cfg.setdefault(k, {}), v)

    # Start the watchdog timer early
    for k, v in cfg["apps"].items():
        if v != "wdt.Cmd":
            continue
        k = cfg.get(k, {})
        if k.get("hw", False):
            machine.WDT(k.get("id", 0), k.get("t", 5000))

    def cfg_network(n):
        import time

        import network

        at("MN1")

        network.hostname(n["name"])
        at("MN2")
        if "country" in n:
            at("MN3")
            network.country(n["country"])
        if "ap" in n:
            at("MN4")
            wlan = network.WLAN(network.STA_IF)  # create station interface
            wlan.active(True)
            if "addr" in n:
                at("MN5")
                nm = n.get("netmask", 24)
                if isinstance(nm, int):
                    ff = (1 << 32) - 1
                    nm = (ff << (32 - nm)) & ff
                    nm = f"{(nm >> 24) & 0xFF}.{(nm >> 16) & 0xFF}.{(nm >> 8) & 0xFF}.{nm & 0xFF}"
                at("MN6")
                wlan.ifconfig((n["addr"], n["netmask"], n["router"], n["dns"]))
            at("MN7")
            wlan.connect(n["ap"], n.get("pwd", ""))  # connect to an AP
        else:
            at("MN8")
            wlan = network.WLAN(network.AP_IF)  # create a station interface
        at("MN9")

        n = 0
        if wlan.isconnected():
            at("MN10")
            return
        at("MN11")
        print("WLAN", end="", file=sys.stderr)
        while not wlan.isconnected():
            if n > 300:
                print(" - no connection", file=sys.stderr)
                raise RuntimeError("no network link")
            n += 1
            time.sleep(0.1)
            print(".", end="", file=sys.stderr)
        at("MN12")
        print(" -", wlan.ifconfig()[0], file=sys.stderr)

    if "net" in cfg and cfg["net"].get("name", None) is not None:
        at("M3")
        cfg_network(cfg["net"])
        at("M9")

    async def _main():
        at("MA1")
        import sys

        from moat.micro.cmd.tree.dir import Dispatch
        from moat.util.compat import idle

        at("MA2")
        async with Dispatch(cfg, i=i) as dsp, TaskGroup() as tg:
            at("MA3")
            tg.start_soon(dsp.task)
            if L:
                at("MA4")
                await dsp.wait_ready()
            else:
                at("MA5")
                await sleep_ms(1000)
            at("MA6")
            if fake_end:
                at("MA7")
                sys.stdout.write("OK\x04\x04>")
            at("MA8")
            await idle()

    at("M5")
    from moat.util.compat import run

    at("M6")
    run(_main)
