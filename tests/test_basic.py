from __future__ import annotations

import pytest
import anyio
from tests.scaffold import scaffold


@pytest.mark.anyio
async def test_basic():
    async def handle(msg):
        assert tuple(msg.msg) == ("Test", 123)
        return {"R": tuple(msg.msg)}

    async with scaffold(handle, None) as (a, b):
        # note the comma
        (res,) = await b.cmd("Test", 123)
        assert res == {"R": ("Test", 123)}


@pytest.mark.anyio
async def test_more():
    async def handle(msg):
        assert msg.msg[0] == "X"
        await anyio.sleep(msg.msg[1] / 10)
        return msg.msg[1]

    async with scaffold(handle, None) as (a, b):
        # note the comma
        r = []
        async with anyio.create_task_group() as tg:

            async def tx(i):
                nonlocal r
                (res,) = await b.cmd("X", i)
                r.append(res)

            # well that's one way to sort an array
            tg.start_soon(tx, 5)
            tg.start_soon(tx, 4)
            tg.start_soon(tx, 3)
            tg.start_soon(tx, 2)
            tg.start_soon(tx, 1)
        assert r == [1, 2, 3, 4, 5]


@pytest.mark.anyio
async def test_return():
    async def handle(msg):
        assert tuple(msg.msg) == ("Test", 123)
        return ("Foo", 234)

    async with scaffold(handle, None) as (a, b):
        res = await b.cmd("Test", 123)
        # note the index
        assert res[0] == ("Foo", 234)


@pytest.mark.anyio
async def test_return2():
    async def handle(msg):
        assert tuple(msg.msg) == ("Test", 123)
        await msg.result("Foo", 234)

    async with scaffold(handle, None) as (a, b):
        # neither a comma nor an index here
        res = await b.cmd("Test", 123)
        assert res == ("Foo", 234)
        print("DONE")


@pytest.mark.anyio
async def test_stream_in():
    async def handle(msg):
        res = []
        assert tuple(msg.msg) == ("Test", 123)
        async with msg.stream_r("Gimme") as st:
            async for m in st:
                assert len(m[1]) == m[0]
                res.append(m[0])
            await msg.result("OK", len(res) + 1)
        assert res == [1, 3, 2]

    async with scaffold(handle, None) as (a, b):
        async with b.stream_w("Test", 123) as st:
            assert tuple(st.msg) == ("Gimme",)
            await st.send(1, "a")
            await st.send(3, "def")
            await st.send(2, "bc")
        assert tuple(st.msg) == ("OK", 4)
        print("DONE")


@pytest.mark.anyio
async def test_stream_out():
    async def handle(msg):
        assert tuple(msg.msg) == ("Test", 123)
        async with msg.stream_w("Takeme") as st:
            await st.send(1, "a")
            await st.send(3, "def")
            await st.send(2, "bc")
            await msg.result("OK", 4)

    async with scaffold(handle, None) as (a, b):
        n = 0
        async with b.stream_r("Test", 123) as st:
            assert tuple(st.msg) == ("Takeme",)
            async for m in st:
                assert len(m[1]) == m[0]
                n += 1
        assert tuple(st.msg) == ("OK", 4)
        assert n == 3
        print("DONE")
