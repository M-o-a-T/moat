from __future__ import annotations

import pytest
import anyio
from tests.scaffold import scaffold
from moat.util import ungroup, OptCtx
from moat.lib.cmd import NoStream


@pytest.mark.anyio
@pytest.mark.parametrize("no_s", [False, True])
async def test_no_stream_in(no_s):
    async def handle(msg):
        assert tuple(msg.msg) == ("Test", 123)
        if no_s:
            await msg.no_stream()
            assert False, "Oops"
        await anyio.sleep(0.1)
        await msg.result("Nope")

    with OptCtx(pytest.raises(NoStream) if no_s else None):
        async with ungroup, scaffold(handle, None) as (a, b):
            async with b.stream_w("Test", 123) as st:
                assert tuple(st.msg) == ("Nope",)
                await anyio.sleep(0.05)
                await st.send(1, "a")
                await anyio.sleep(0.05)
                await st.send(3, "def")
                await anyio.sleep(0.05)
                await st.send(2, "bc")
            if no_s:
                assert False, "Oops"
            assert tuple(st.msg) == ("Nope",)


@pytest.mark.anyio
@pytest.mark.parametrize("no_s", [False, True])
async def test_no_stream_out(no_s):
    async def handle(msg):
        assert tuple(msg.msg) == ("Test", 123)
        if no_s:
            await msg.no_stream()
            assert False, "Oops"
        await anyio.sleep(0.2)
        await msg.result("Nope")

    with OptCtx(pytest.raises(NoStream) if no_s else None):
        async with ungroup, scaffold(handle, None) as (a, b):
            n = 0
            async with b.stream_r("Test", 123) as st:
                assert tuple(st.msg) == ("Nope",)
                async for m in st:
                    assert len(m[1]) == m[0]
                    n += 1
            if no_s:
                assert False, "Oops"
            assert tuple(st.msg) == ("Nope",)
            assert n == 0
            print("DONE")


@pytest.mark.anyio
async def test_write_both():
    async def handle(msg):
        assert tuple(msg.msg) == ("Test", 123)
        async with msg.stream_w("Takeme") as st:
            await st.send(1, "a")
            await anyio.sleep(0.05)
            await st.send(3, "def")
            await anyio.sleep(0.05)
            await st.send(2, "bc")
            await msg.result("OK", 4)

    with pytest.raises(NoStream):
        async with ungroup, scaffold(handle, None) as (a, b):
            async with b.stream_w("Test", 123) as st:
                assert tuple(st.msg) == ("Takeme",)
                await st.send(1, "a")
                await anyio.sleep(0.05)
                await st.send(3, "def")
                await anyio.sleep(0.05)
                await st.send(2, "bc")
            assert tuple(st.msg) == ("OK", 4)
            print("DONE")
