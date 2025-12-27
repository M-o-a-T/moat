#!/usr/bin/python3
"""
RPC example, local
"""

from __future__ import annotations

import anyio

from moat.lib.rpc import MsgHandler, MsgSender

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.lib.rpc import Msg


class Called(MsgHandler):
    """
    A MsgHandler is the object that receives streamed commands and calls
    `handle_command` to process them.

    The associated MsgSender is responsible for serializing each call from
    Python into a Msg object.
    """

    async def handle(self, msg: Msg, *_a):
        "a very simple command handler"
        if msg.cmd[0] == "Start":
            return await msg.result("OK starting")

        if msg.cmd[0] == "gimme data":
            async with msg.stream_out("Start") as st:
                for i in range(10):
                    await st.send(i + msg.kw["x"])
                return await msg.result("OK I'm done")

        if msg.cmd[0] == "alive":
            async with msg.stream_in("Start") as st:
                async for data in st:
                    print("We got", data)
                return await msg.result("OK nice")

        raise ValueError(f"Unknown: {msg!r}")


async def example():
    "A simple RPC example"
    srv = Called()
    # A MsgHandler by itself doesn't need, or indeed have, a context
    # manager; parallelism is handled by the individual `async with
    # client.cmd` contexts, below, if required.
    client = MsgSender(srv)

    (res,) = await client.cmd("Start")
    assert res.startswith("OK")

    async with client.cmd("gimme data", x=5).stream_in(5) as st:
        assert st.args[0] == "Start", st.args
        async for (nr,) in st:
            print(nr)  # 5, 6, .. 14
    assert st.args[0] == "OK I'm done", st.args

    async with client.cmd("alive").stream_out() as st:
        for i in range(3):
            await st.send(i)
    assert st.args[0] == "OK nice", st.args


anyio.run(example)
