"""
Basic test using a MicroPython subtask
"""
import pytest

pytestmark = pytest.mark.anyio

from moat.micro._test import mpy_client, mpy_server

TT = 250  # XXX assume that this is OK


async def test_bms(tmp_path):
    "Basic BMS test"
    ended = False
    async with mpy_server(tmp_path) as obj:
        async with mpy_client(obj) as req:
            res = await req.send("ping", "hello")
            assert res == "R:hello"
            ended = True

            s = await req.send(["loc","bat1","state"])
            print(s)

    assert ended
