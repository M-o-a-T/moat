"""
Test program cloned from asyncowfs, but using DistKV for end-to-semi-end testing.
"""
import sys
import trio
import anyio
import pytest
from copy import deepcopy
from functools import partial

from asyncowfs.mock import some_server, structs
from distkv.mock import run
from distkv.mock.mqtt import stdtest

from distkv.ext import load_ext
from distkv.util import attrdict, data_get, Path, P

owfs_mock = load_ext("owfs","mock")

import logging
logger = logging.getLogger(__name__)

# We can just use 'async def test_*' to define async tests.
# This also uses a virtual clock fixture, so time passes quickly and
# predictably.

basic_tree = {
    "bus.0":
        {
            "alarm": {},
            "simultaneous": {
                "temperature": 0,
                },
            "10.345678.90":
                {
                    "latesttemp": "12.5",
                    "templow": "15",
                    "temphigh": "20",
                }
        },
    "structure": structs,
}

async def test_alarm(mock_clock):
    mock_clock.autojump_threshold = 0.1
    my_tree = deepcopy(basic_tree)
    dt = my_tree['bus.0']['10.345678.90']
    async with stdtest(test_0={"init": 125}, n=1, tocks=200) as st, st.client(0) as client:
        evt = anyio.create_event()
        obj = attrdict(client=client,meta=0,stdout=sys.stdout)
        await st.tg.spawn(partial(owfs_mock['server'], client, tree=my_tree, evt=evt))
        await evt.wait()
        await st.run("owfs attr -d 10.345678.90 -i 5 temperature test.foo.temp")
        await anyio.sleep(10)
        await data_get(obj,Path())

        res = await client.get(P("test.foo.temp"))
        assert res.value == 12.5
        dt["latesttemp"] = 42
        await anyio.sleep(6)
        res = await client.get(P("test.foo.temp"))
        await data_get(obj,Path())
        assert res.value == 42

        await st.tg.cancel_scope.cancel()

