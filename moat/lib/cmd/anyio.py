"""
cmdhandler on top of anyio pipe
"""

import anyio
from contextlib import asynccontextmanager
from moat.lib.cmd import CmdHandler
from moat.util.cbor import StdCBOR


@asynccontextmanager
async def run(cmd: CmdHandler, stream: anyio.abc.ByteStream):
    """
    Run a command handler on top of an anyio stream.

    The handler must already be set up.

    This is an async context manager that yields the command handler.
    """

    async def rd(conn):
        unpacker = StdCBOR()
        rd = conn.read if hasattr(conn,"read") else conn.receive
        while True:
            buf = await rd(4096)
            for msg in unpacker.feed(buf):
                await cmd.msg_in(msg)

    async def wr(conn):
        packer = StdCBOR()
        wr = conn.write if hasattr(conn,"write") else conn.send
        while True:
            msg = await cmd.msg_out()
            buf = packer.encode(msg)
            await wr(buf)

    async with cmd, anyio.create_task_group() as tg:
        tg.start_soon(rd, stream)
        tg.start_soon(wr, stream)
        yield cmd
