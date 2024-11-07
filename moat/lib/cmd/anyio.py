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
        while True:
            buf = await conn.read(4096)
            for msg in unpacker.feed(buf):
                await cmd.msg_in(msg)

    async def wr(conn):
        packer = StdCBOR()
        while True:
            msg = await cmd.msg_out()
            buf = packer.encode(msg, cbor=True)
            await conn.write(buf)

    async with anyio.create_task_group() as tg:
        tg.start_soon(rd, stream)
        tg.start_soon(wr, stream)
        yield cmd
