from __future__ import annotations

import pytest
from tests.scaffold import scaffold

@pytest.mark.anyio
async def test_basic():
    async def handle(msg):
        assert tuple(msg.msg) == ("Test",123)
        return {"R":tuple(msg.msg)}

    async with scaffold(handle,None) as (a,b,tg):
        res, = await b.cmd("Test",123)
        assert res == {"R":("Test",123)}
        print("DONE")


@pytest.mark.anyio
async def test_stream_in():
    async def handle(msg):
        res = []
        assert tuple(msg.msg) == ("Test",123)
        async with msg.stream_r("Gimme") as st:
            async for m in st:
                assert len(m[1]) == m[0]
                res.append(m[0])
            await msg.result("OK", len(res)+1)
        assert res == [1,3,2]

    async with scaffold(handle,None) as (a,b,tg):
        async with b.stream_w("Test", 123) as st:
            assert tuple(st.msg) == ("Gimme",)
            await st.send(1,"a")
            await st.send(3,"def")
            await st.send(2,"bc")
        assert tuple(st.msg) == ("OK",4)
        print("DONE")


@pytest.mark.anyio
async def test_stream_out():
    async def handle(msg):
        assert tuple(msg.msg) == ("Test",123)
        async with msg.stream_w("Takeme") as st:
            await st.send(1,"a")
            await st.send(3,"def")
            await st.send(2,"bc")
            await msg.result("OK", 4)

    async with scaffold(handle,None) as (a,b,tg):
        n = 0
        async with b.stream_r("Test", 123) as st:
            assert tuple(st.msg) == ("Takeme",)
            async for m in st:
                assert len(m[1]) == m[0]
                n += 1
        assert tuple(st.msg) == ("OK",4)
        assert n == 3
        print("DONE")


