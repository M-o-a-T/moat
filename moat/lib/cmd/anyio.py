"""
cmdhandler on top of anyio pipe
"""
import anyio
from moat.lib.cmd import CmdHandler
from moat.util.cbor import StdCBOR

async def run(cmd: CmdHandler, stream:anyio.abc.ByteStream):
    packer = StdCBOR()

    async def rd(conn):
        unpacker = StdCBOR()
        while True:
            buf = await conn.read(4096)
            for msg in unpack.feed(buf):
                await self._cmd.msg_in(msg)

    async def wr(conn):
        packer = StdCBOR()
        while True:
            msg = await self._cmd.msg_out()
            buf = packer.encode(msg, cbor=True)
            await conn.write(buf)

    async with anyio.create_task_group() as tg:
        tg.start_soon(rd, stream)
        tg.start_soon(wr, stream)

