from __future__ import annotations  # noqa: D100

import anyio
import pytest

from moat.lib.cmd.base import MsgHandler, MsgSender
from moat.lib.cmd.nest import run as nested


@pytest.mark.anyio
async def test_basic_handle():  # noqa: D103
    evt1 = anyio.Event()
    evt2 = anyio.Event()

    class CmdI(MsgHandler):
        def __init__(self, evt):
            self.evt = evt

        async def cmd_yes(self, yeah):
            if yeah:
                self.evt.set()
            return yeah * 10

    class EP(MsgHandler):
        async def stream_Test(self, msg):
            async with msg.stream(), nested(CmdI(evt1), msg, debug="B") as cmdo:
                (res,) = await MsgSender(cmdo).cmd("yes", 1)
                await evt1.wait()
                assert res == 10

    ep = EP()
    ms = MsgSender(ep)
    async with ms.cmd("Test").stream() as msg, nested(CmdI(evt2), msg, debug="A") as cmdo:
        (res,) = await MsgSender(cmdo).cmd("yes", 2)
        await evt2.wait()
        assert res == 20
