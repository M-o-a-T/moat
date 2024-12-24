from __future__ import annotations

import pytest
import anyio
from moat.lib.cmd import StreamError
from tests.lib_cmd.scaffold import scaffold


@pytest.mark.anyio
@pytest.mark.parametrize("a_s", [(), ("foo"), (12, 34)])
@pytest.mark.parametrize("a_r", [(), ("bar"), (2, 3)])
@pytest.mark.parametrize("k_s", [{}, dict(a=42)])
@pytest.mark.parametrize("k_r", [{}, dict(b=21)])
async def test_basic(a_s, a_r, k_s, k_r):
    async def handle(msg):
        assert msg.cmd == "Test"
        assert tuple(msg.args) == tuple(a_s)
        if not msg.kw:
            assert not k_s
        else:
            assert msg.kw == k_s
        await msg.result(*a_r, **k_r)

        return {"C": msg.cmd, "R": tuple(msg.args)}

    async with scaffold(handle, None) as (a, b):
        # note the comma
        res = await b.cmd("Test", *a_s, **k_s)
        assert tuple(res.args) == tuple(a_r)
        assert res.kw == k_r


@pytest.mark.anyio
async def test_basic_res():
    async def handle(msg):
        assert msg.cmd == "Test"
        assert tuple(msg.args) == (123,)
        return {"C": msg.cmd, "R": tuple(msg.args)}

    async with scaffold(handle, None) as (a, b):
        # note the comma
        (res,) = await b.cmd("Test", 123)
        assert res == {"C": "Test", "R": (123,)}


@pytest.mark.anyio
async def test_error():
    async def handle(msg):
        raise RuntimeError("Duh", msg.args)

    async with scaffold(handle, None) as (a, b):
        with pytest.raises(StreamError) as err:
            res = await b.cmd("Test", 123)
            print(f"OWCH: result is {res!r}")
        assert err.match("123")
        assert err.match("Duh")


@pytest.mark.anyio
async def test_more():
    async def handle(msg):
        assert msg.cmd == "X"
        await anyio.sleep(msg.args[0] / 10)
        return msg.args[0]

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
        assert msg.cmd == "Test"
        assert tuple(msg.args) == (123,)
        return ("Foo", 234)

    async with scaffold(handle, None) as (a, b):
        res = await b.cmd("Test", 123)
        # note the index
        assert res[0] == ("Foo", 234)


@pytest.mark.anyio
async def test_return2():
    async def handle(msg):
        assert msg.cmd == "Test"
        assert tuple(msg.args) == (123,)
        await msg.result("Foo", 234)

    async with scaffold(handle, None) as (a, b):
        # neither a comma nor an index here
        res = await b.cmd("Test", 123)
        assert res.args == ["Foo", 234]
        print("DONE")


@pytest.mark.anyio
async def test_stream_in():
    async def handle(msg):
        res = []
        assert msg.cmd == "Test"
        assert tuple(msg.args) == (123,)
        async with msg.stream_r() as st:
            async for m in st:
                assert len(m[1]) == m[0]
                res.append(m[0])
            await msg.result("OK", len(res) + 1)
        assert res == [1, 3, 2]

    async with scaffold(handle, None) as (a, b):
        async with b.stream_w("Test", 123) as st:
            assert tuple(st.args) == ()
            await st.send(1, "a")
            await st.send(3, "def")
            await st.send(2, "bc")
        assert tuple(st.args) == ("OK", 4)
        print("DONE")


@pytest.mark.anyio
async def test_stream_out():
    async def handle(msg):
        assert msg.cmd == "Test"
        assert tuple(msg.args) == (123, 456)
        assert msg.kw["answer"] == 42, msg.kw
        async with msg.stream_w("Takeme") as st:
            await st.send(1, "a")
            await st.send(3, "def")
            await st.send(2, "bc")
            await msg.result({})

    async with scaffold(handle, None) as (a, b):
        n = 0
        async with b.stream_r("Test", 123, 456, answer=42) as st:
            assert tuple(st.args) == ("Takeme",)
            async for m in st:
                assert len(m[1]) == m[0]
                n += 1
        assert tuple(st.args) == ({},)
        assert not st.kw
        assert n == 3
        print("DONE")
