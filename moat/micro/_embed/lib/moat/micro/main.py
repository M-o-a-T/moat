"""
Main entry point for satellites.

Called from the root "main.py".
"""

from __future__ import annotations

import sys

from moat.util import merge
from moat.util.compat import L, TaskGroup, sleep_ms
from rtc import all_rtc

from moat.lib.codec.cbor import Codec as CBOR

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
    if isinstance(cfg, str):
        try:
            f = open(cfg, "rb")  # noqa:SIM115
        except OSError:
            raise OSError(cfg) from None
        with f:
            cfg = CBOR().decode(f.read())

    # Update config from RTC memory, if present
    if not i.fb:
        for k, v in all_rtc():
            merge(cfg.setdefault(k, {}), v)

    def cfg_network(n):
        import time

        import network

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
            time.sleep(0.1)
            print(".", end="", file=sys.stderr)
        print(" -", wlan.ifconfig()[0], file=sys.stderr)

    if "net" in cfg and cfg["net"].get("name", None) is not None:
        cfg_network(cfg["net"])

    async def _main():
        import sys

        from moat.micro.cmd.tree.dir import Dispatch
        from moat.util.compat import idle

        async with Dispatch(cfg, i=i) as dsp, TaskGroup() as tg:
            tg.start_soon(dsp.task)
            if L:
                await dsp.wait_ready()
            else:
                await sleep_ms(1000)
            if fake_end:
                sys.stdout.write("OK\x04\x04>")
            await idle()

    from moat.util.compat import run

    run(_main)
