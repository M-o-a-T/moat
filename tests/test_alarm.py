"""
Test program cloned from asyncowfs, but using DistKV for end-to-semi-end testing.
"""
import sys
import anyio
from copy import deepcopy
from functools import partial

from asyncowfs.mock import structs
from distkv.mock.mqtt import stdtest

from moat.util import attrdict, Path, P, load_ext
from distkv.data import data_get

owfs_mock = load_ext("distkv_ext.owfs", "mock")

import logging

logger = logging.getLogger(__name__)

# We can just use 'async def test_*' to define async tests.
# This also uses a virtual clock fixture, so time passes quickly and
# predictably.

basic_tree = {
    "bus.0": {
        "alarm": {},
        "simultaneous": {"temperature": 0},
        "10.345678.90": {
            "latesttemp": "12.5",
            "temperature": "12.5",
            "templow": "15",
            "temphigh": "20",
            "foo": {"bar": 123, "plugh.A": 1, "plugh.B": 2, "plugh.C": 3},
        },
    },
    "structure": structs,
}


async def test_alarm(mock_clock):
    mock_clock.autojump_threshold = 0.1
    my_tree = deepcopy(basic_tree)
    dt = my_tree["bus.0"]["10.345678.90"]
    async with stdtest(test_0={"init": 125}, n=1, tocks=200) as st, st.client(0) as client:
        evt = anyio.create_event()
        obj = attrdict(client=client, meta=0, stdout=sys.stdout)
        await st.tg.spawn(partial(owfs_mock.server, client, tree=my_tree, evt=evt))
        await evt.wait()
        assert dt["foo"]["bar"] == 123
        await st.run("owfs attr -d 10.345678.90 -i 5 temperature test.foo.temp")
        await st.run("owfs attr -d 10.345678.90 -w templow test.foo.low")
        await st.run("owfs attr -d 10.345678.90 -w foo.bar -a bar:1 test.foo.what.ever")
        await st.run("owfs attr -d 10.345678.90 -i 4 -a baz:2 foo.plugh:1 test.foo.this")
        res = await client.set(P("test.foo.this"), value={"this": "is", "baz": {3: 33}})
        await anyio.sleep(10)
        await data_get(obj, Path())

        await client.set(P("test.foo.low"), 11)
        await client.set(P("test.foo.what.ever"), {"Hello": "No", "bar": {0: 99, 1: 13}})
        await anyio.sleep(1)
        res = await client.get(P("test.foo.temp"))
        assert res.value == 12.5
        dt["latesttemp"] = 42
        dt["temperature"] = 42
        dt["foo"]["plugh.B"] = 22
        await anyio.sleep(6)
        res = await client.get(P("test.foo.temp"))
        await data_get(obj, Path())
        assert res.value == 42
        assert dt["foo"]["bar"] == "13"
        res = await client.get(P("test.foo.this"))
        assert res.value == {"this": "is", "baz": {2: 22, 3: 33}}

        await st.tg.cancel_scope.cancel()
