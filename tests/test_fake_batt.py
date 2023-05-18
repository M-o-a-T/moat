"""
Basic test using a MicroPython subtask
"""
import pytest
from moat.micro._test import mpy_client, mpy_server  # pylint:disable=E0401,E0611
from moat.util.compat import ticks_add, ticks_diff, ticks_ms

pytestmark = pytest.mark.skip
# pytestmark = pytest.mark.anyio

TT = 250  # XXX assume that this is OK


async def test_bms(tmp_path):
    "Basic BMS test"
    ended = False
    async with mpy_server(tmp_path) as obj:
        async with mpy_client(obj) as req:
            res = await req.send("ping", "hello")
            assert res == "R:hello"
            ended = True

            s = await req.send(["local", "bat1", "state"])
            print(s)

            t = ticks_add(ticks_ms(), -2000)
            for _ in range(3):
                res = await req.send(("local", "sq"), o=("bat1", "ui"))
                tn = ticks_ms()
                assert 1900 < ticks_diff(tn, t) < 2100, (tn, t)
                print(res)

    assert ended
