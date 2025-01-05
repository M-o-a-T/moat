from __future__ import annotations
import anyio
from moat.lib.cmd import CmdHandler
from contextlib import asynccontextmanager
import logging

logger = logging.getLogger(__name__)


@asynccontextmanager
async def scaffold(ha, hb, key=""):
    async def cp(src, dst, d):
        while True:
            msg = await src.msg_out()
            logger.debug("%s %r", d, msg)
            if isinstance(msg, tuple):
                msg = list(msg)
            await dst.msg_in(msg)

    async with (
        anyio.create_task_group() as tg,
        CmdHandler(ha) as a,
        CmdHandler(hb) as b,
    ):
        tg.start_soon(cp, a, b, f"{key}>")
        tg.start_soon(cp, b, a, f"{key}<")
        yield a, b
        tg.cancel_scope.cancel()
    assert not a._msgs, a._msgs
    assert not b._msgs, b._msgs
