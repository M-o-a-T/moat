"""
Basic test using a MicroPython subtask
"""
import pytest

pytestmark = pytest.mark.anyio

import os
import sys

import anyio

from . import mpy_client, mpy_server
from moat.micro.compat import sleep_ms
from moat.util import NotGiven

TT=250  # XXX assume that this is OK

async def test_wdt(tmp_path):
    ended = False
    with pytest.raises(EOFError):
        async with mpy_server(tmp_path) as obj:
            async with mpy_client(obj) as req:
                res = await req.send("ping", "hello")
                assert res == "R:hello"

                # XXX unfortunately we can't test ext=False or hw=True on Linux
                await req.set_cfg({
                        "apps": {"w1":"wdt.WDTCmd"},
                        "w1": dict(t=TT, ext=True, hw=False),
                    }, sync=True)
                await sleep_ms(TT/2)
                await req.send(["w1","x"])
                await sleep_ms(TT/2)
                await req.send(["w1","x"])
                ended = True
                await sleep_ms(TT*1.5)
                raise RuntimeError("didn't die")
    assert ended

async def test_wdt_off(tmp_path):
    """
    Check that the watchdog can be removed
    """
    async with mpy_server(tmp_path) as obj:
        async with mpy_client(obj) as req:
            await req.set_cfg({
                    "apps": {"w1":"wdt.WDTCmd"},
                    "w1": dict(t=TT, ext=True, hw=False),
                }, sync=True)
            await sleep_ms(TT/2)
            await req.send(["w1","x"])
            await sleep_ms(TT/2)
            await req.send(["w1","x"])
            await req.set_cfg({
                    "apps": {"w1":NotGiven},
                }, sync=True)
            await sleep_ms(TT*2)

async def test_wdt_update(tmp_path):
    """
    Check that the watchdog can be updated
    """
    ended = False
    with pytest.raises(EOFError):
        async with mpy_server(tmp_path) as obj:
            async with mpy_client(obj) as req:
                await req.set_cfg({
                        "apps": {"w1":"wdt.WDTCmd"},
                        "w1": dict(t=TT, ext=True, hw=False),
                    }, sync=True)
                await sleep_ms(TT/2)
                await req.send(["w1","x"])
                await sleep_ms(TT/2)
                await req.send(["w1","x"])
                await req.set_cfg({"w1": dict(t=TT*3)}, sync=True)
                await sleep_ms(TT*2)
                await req.send(["w1","x"])
                await sleep_ms(TT*2)
                await req.send(["w1","x"])
                ended = True
                await sleep_ms(TT*4)
                raise RuntimeError("didn't die")
    assert ended

