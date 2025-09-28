from __future__ import annotations  # noqa: D100

import pytest
import anyio
from moat.util import P
from moat.util.compat import log
from tests.moat_lib_cmd.scaffold import scaffold
from moat.lib.cmd.base import MsgSender, MsgHandler


@pytest.mark.anyio
@pytest.mark.parametrize(
    "a_s",
    [
        [],
        [
            None,
        ],
        ["foo"],
        [12, 34],
    ],
)
@pytest.mark.parametrize(
    "a_r",
    [
        [],
        [
            None,
        ],
        ["bar"],
        [2, 3],
    ],
)
@pytest.mark.parametrize("k_s", [{}, dict(a=42)])
@pytest.mark.parametrize("k_r", [{}, dict(b=21)])
async def test_basic_handle(a_s, a_r, k_s, k_r):  # noqa: D103
    class EP(MsgHandler):
        async def stream_Test(self, msg):
            assert msg.cmd == P("Test")
            assert tuple(msg.args) == tuple(a_s)
            if not msg.kw:
                assert not k_s
            else:
                assert msg.kw == k_s
            await msg.result(*a_r, **k_r)

    ep = EP()
    ms = MsgSender(ep)
    res = await ms.cmd("Test", *a_s, **k_s)

    assert list(res.args) == a_r
    assert res.kw == k_r


@pytest.mark.anyio
async def test_basic_error():
    "check error handling"

    class EP(MsgHandler):
        async def stream_Err(self, msg):  # noqa: ARG002
            raise RuntimeError("Duh")

    ep = EP()
    ms = MsgSender(ep)
    with pytest.raises(RuntimeError) as err:
        res = await ms.cmd("Err")


@pytest.mark.anyio
@pytest.mark.parametrize("a_s", [(), (None,), ("foo"), (12, 34)])
@pytest.mark.parametrize("a_r", [(), (None,), ("bar"), (2, 3)])
@pytest.mark.parametrize("k_s", [{}, dict(a=42)])
@pytest.mark.parametrize("k_r", [{}, dict(b=21)])
async def test_basic_scaffold(a_s, a_r, k_s, k_r):  # noqa: D103
    class EP(MsgHandler):
        @staticmethod
        async def handle(msg, rcmd):
            rcmd  # noqa:B018
            assert msg.cmd == P("Test")
            assert tuple(msg.args) == tuple(a_s)
            if not msg.kw:
                assert not k_s
            else:
                assert msg.kw == k_s
            await msg.result(*a_r, **k_r)

    async with scaffold(EP, None) as (a, b):
        a._id = 9  # noqa: SLF001
        b._id = 12  # noqa: SLF001
        res = await b.cmd("Test", *a_s, **k_s)
        assert tuple(res.args) == tuple(a_r)
        assert res.kw == k_r


@pytest.mark.anyio
async def test_error_scaffold():  # noqa: D103
    class EP(MsgHandler):
        @staticmethod
        async def handle(msg, rcmd):
            msg, rcmd  # noqa:B018
            raise RuntimeError("Duh")

    async with scaffold(EP(), None) as (a, b):
        a._id = 9  # noqa: SLF001
        b._id = 12  # noqa: SLF001
        with pytest.raises(RuntimeError) as err:
            res = await b.cmd("Err")
            raise ValueError("No error", res.args, res.kw)
        assert err.value.args == ("Duh",), err.value


@pytest.mark.anyio
async def test_basic_res():  # noqa: D103
    ncall = 0

    class EP(MsgHandler):
        @staticmethod
        async def handle(msg, rcmd):
            rcmd  # noqa:B018
            assert msg.cmd == P("Test")
            assert tuple(msg.args) == (123,)
            nonlocal ncall
            ncall += 1
            await msg.result({"C": msg.cmd, "R": tuple(msg.args)})

    async with scaffold(EP(), None) as (a, b):
        # note the comma
        res = await b.cmd("Test", 123)  # fmt:skip  ## (res,) = …
        (res,) = res
        assert res == {"C": P("Test"), "R": (123,)}
        assert ncall == 1


@pytest.mark.anyio
async def test_error():  # noqa: D103
    class EP(MsgHandler):
        @staticmethod
        async def handle(msg, rcmd):
            rcmd  # noqa:B018
            raise RuntimeError("Duh", msg.args)

    async with scaffold(EP(), None) as (a, b):
        with pytest.raises(RuntimeError) as err:
            res = await b.cmd("Test", 123)
            print(f"OWCH: result is {res!r}")
        assert err.match("123")
        assert err.match("Duh")


@pytest.mark.anyio
async def test_more():  # noqa: D103
    class EP(MsgHandler):
        @staticmethod
        async def handle(msg, rcmd):
            rcmd  # noqa:B018
            assert msg.cmd == ["X"]
            await anyio.sleep(msg.args[0] / 10)
            await msg.result(msg[0])

    async with scaffold(EP(), None) as (a, b):
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
async def test_return():  # noqa: D103
    class EP(MsgHandler):
        @staticmethod
        async def handle(msg, rcmd):
            rcmd  # noqa:B018
            assert msg.cmd == P("Test")
            assert tuple(msg.args) == (123,)
            await msg.result(("Foo", 234))

    async with scaffold(EP(), None) as (a, b):
        res = await b.cmd("Test", 123)
        # note the index
        assert res[0] == ("Foo", 234)


@pytest.mark.anyio
async def test_return2():  # noqa: D103
    class EP(MsgHandler):
        @staticmethod
        async def handle(msg, rcmd):
            rcmd  # noqa:B018
            assert msg.cmd == P("Test")
            assert tuple(msg.args) == (123,)
            await msg.result("Foo", 234)

    async with scaffold(EP(), None) as (a, b):
        # neither a comma nor an index here
        res = await b.cmd("Test", 123)
        assert res.args == ["Foo", 234]
        print("DONE")


@pytest.mark.anyio
@pytest.mark.parametrize("use_socket", [False, True])
async def test_stream_in(use_socket):  # noqa: D103
    class EP(MsgHandler):
        @staticmethod
        async def handle(msg, rcmd):
            rcmd  # noqa:B018
            res = []
            assert msg.cmd == P("Test")
            assert tuple(msg.args) == (123,)
            log("MSIN %d", id(msg))
            async with msg.stream_in("LetsGo") as st:
                async for m in st:
                    assert len(m[1]) == m[0]
                    res.append(m[0])
                await msg.result("OK", len(res) + 1)
            assert res == [1, 3, 2]

    async with scaffold(EP(), None, use_socket=use_socket) as (a, b):
        async with b.cmd("Test", 123).stream_out() as st:
            assert tuple(st.args) == ("LetsGo",)
            await st.send(1, "a")
            await st.send(3, "def")
            await st.send(2, "bc")
        assert tuple(st.args) == ("OK", 4)
        print("DONE")


@pytest.mark.anyio
@pytest.mark.parametrize("use_socket", [False, True])
async def test_stream_out(use_socket):  # noqa: D103
    class EP(MsgHandler):
        @staticmethod
        async def handle(msg, rcmd):
            rcmd  # noqa:B018
            assert msg.cmd == P("Test")
            assert tuple(msg.args) == (123, 456)
            assert msg.kw["answer"] == 42, msg.kw
            async with msg.stream_out("Takeme") as st:
                await st.send(1, "a")
                await st.send(3, "def")
                await st.send(2, "bc")
                await msg.result({})

    async with scaffold(EP(), None, use_socket=use_socket) as (a, b):
        n = 0
        async with b.cmd("Test", 123, 456, answer=42).stream_in() as st:
            assert tuple(st.args) == ("Takeme",)
            async for m in st:
                assert len(m[1]) == m[0]
                n += 1
        assert tuple(st.args) == ({},)
        assert not st.kw
        assert n == 3
