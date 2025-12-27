#!/usr/bin/python3
"""
RPC example, via TCP.
"""

from __future__ import annotations

import anyio
import logging
from contextlib import asynccontextmanager

from moat.lib.rpc import MsgHandler, MsgSender, rpc_on_aiostream

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.lib.rpc import Msg

    from collections.abc import AsyncGenerator
    from typing import Self

logger = logging.getLogger("example")
logging.basicConfig(level=logging.DEBUG)


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


class ExtServer(anyio.AsyncContextManagerMixin):
    """
    A simple server, as a context manager that yields the address
    for connecting to it.
    """

    @staticmethod
    async def hdl(client):
        """
        Client connection handler.

        Uses a `Called` to handle incoming messages.
        """
        async with client, rpc_on_aiostream(Called(), client, codec="cbor") as rpc:
            rpc  # noqa:B018
            # we don't actively send things, so doing nothing further here.
            # Otherwise we'd create a MsgSender(rpc) next.
            await anyio.sleep_forever()

    @asynccontextmanager
    async def __asynccontextmanager__(self) -> AsyncGenerator[Self]:
        listener = await anyio.create_tcp_listener(local_host="127.0.0.1")
        # port is zero, thus auto-allocated by the OS
        async with anyio.create_task_group() as tg:
            tg.start_soon(listener.serve, self.hdl)
            addr = listener.extra(anyio.abc.SocketAttribute.raw_socket).getsockname()
            yield addr  # passed back to the client, so we can open a connection
            tg.cancel_scope.cancel()


async def example():
    """
    Create a TCP connection and send fancy data.
    """
    async with (
        ExtServer() as addr,
        await anyio.connect_tcp(*addr) as client,
        rpc_on_aiostream(None, client, codec="cbor", logger=logger) as rpc,
        # we don't handle incoming calls, thus using None.
    ):
        client = MsgSender(rpc)  # noqa:PLW2901

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
