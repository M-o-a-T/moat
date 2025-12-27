from __future__ import annotations  # noqa: D100

import anyio
import pytest

from tests.moat_lib_rpc.scaffold import scaffold

from moat.util import OptCtx, P, ungroup
from moat.lib.rpc.base import MsgHandler
from moat.lib.rpc.errors import NoStream

# TODO no_s=False does no longer work for some reason


@pytest.mark.anyio
@pytest.mark.parametrize("no_s", [True])
async def test_no_stream_in(no_s):  # noqa: D103
    class EP(MsgHandler):
        @staticmethod
        async def handle(msg, rcmd):
            rcmd  # noqa:B018
            assert msg.cmd == P("Test")
            assert tuple(msg.args) == (123,)
            if no_s:
                await msg.no_stream()
                raise AssertionError("Oops")
            await anyio.sleep(0.1)
            await msg.result("Nope")

    with OptCtx(pytest.raises(NoStream) if no_s else None):
        async with ungroup, scaffold(EP(), None) as (_a, b):
            async with b.cmd("Test", 123).stream_out() as st:
                assert tuple(st.args) == ("Nope",)
                await anyio.sleep(0.05)
                await st.send(1, "a")
                await anyio.sleep(0.05)
                await st.send(3, "def")
                await anyio.sleep(0.05)
                await st.send(2, "bc")
            if no_s:
                raise AssertionError("Oops")
            assert tuple(st.args) == ("Nope",)


@pytest.mark.anyio
@pytest.mark.parametrize("no_s", [True])
async def test_no_stream_out(no_s):  # noqa: D103
    class EP(MsgHandler):
        @staticmethod
        async def handle(msg, rcmd):
            rcmd  # noqa:B018
            assert msg.cmd == P("Test")
            assert tuple(msg.args) == (123,)
            if no_s:
                await msg.no_stream()
                raise AssertionError("Oops")
            await anyio.sleep(0.2)
            await msg.result("Nope")

    with OptCtx(pytest.raises(NoStream) if no_s else None):
        async with ungroup, scaffold(EP(), None) as (_a, b):
            n = 0
            async with b.cmd("Test", 123).stream_in() as st:
                assert tuple(st.args) == ("Nope",)
                async for m in st:
                    assert len(m[1]) == m[0]
                    n += 1
            if no_s:
                raise AssertionError("Oops")
            assert tuple(st.args) == ("Nope",)
            assert n == 0
            print("DONE")


@pytest.mark.anyio
async def test_write_both():  # noqa: D103
    class EP(MsgHandler):
        @staticmethod
        async def handle(msg, rcmd):
            rcmd  # noqa:B018
            assert msg.cmd == P("Test")
            assert tuple(msg.args) == (123,)
            async with msg.stream_out("Takeme") as st:
                await st.send(1, "a")
                await anyio.sleep(0.05)
                await st.send(3, "def")
                await anyio.sleep(0.05)
                await st.send(2, "bc")
                await msg.result("OK", 4)

    with pytest.raises(NoStream):  # noqa:PT012
        async with ungroup, scaffold(EP(), None) as (_a, b):
            async with b.cmd("Test", 123).stream_out() as st:
                assert tuple(st.args) == ("Takeme",)
                await st.send(1, "a")
                await anyio.sleep(0.05)
                await st.send(3, "def")
                await anyio.sleep(0.05)
                await st.send(2, "bc")
            assert tuple(st.args) == ("OK", 4)
            print("DONE")
