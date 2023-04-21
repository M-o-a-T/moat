"""
Test reliable retransmission, using various parameters.
"""

import anyio
import pytest

from moat.micro._test import Loop
from moat.micro.compat import TaskGroup
from moat.micro.proto.reliable import Reliable
from moat.micro.proto.stack import Logger, _Stacked

pytestmark = pytest.mark.anyio

done_ = [None] * 4


class Head(_Stacked):
    "sender/receiver test common code"

    def __init__(self, parent, pos, done):
        super().__init__(parent)
        self.pos = pos
        self.done = done


class Xmit(Head):
    "seniding test class"

    async def run(self):
        "main"
        pos = self.pos
        done_[pos] = 0
        async with TaskGroup() as tg:
            for n in range(10):
                await tg.spawn(self.send, dict(n=n, msg="Hey"))
                done_[pos] += 1
        self.done.set()


class Recv(Head):
    "receiving test class"

    async def run(self):
        "main"
        pos = self.pos
        got = 0
        for _ in range(10):
            msg = await self.recv()
            got |= 1 << msg["n"]
        assert got == (2**10) - 1
        done_[pos] = 10
        self.done.set()


# Zero on both sides can deadlock
@pytest.mark.parametrize("qlen1", [2, 20])
@pytest.mark.parametrize("qlen2", [2, 20])
@pytest.mark.parametrize("window", [4, 8, 20])
@pytest.mark.parametrize("loss", [0, 0.1, 0.7])
async def test_basic(qlen1, qlen2, window, loss):
    "basic test for Reliable channel"
    done1 = anyio.Event()
    done2 = anyio.Event()
    l1 = u1 = Loop(qlen=qlen1, loss=loss)
    l2 = u2 = Loop(qlen=qlen2, loss=loss)
    l1.link(l2)
    l2.link(l1)
    u1 = u1.stack(Logger, txt="L1")
    u2 = u2.stack(Logger, txt="L2")
    r1 = u1.stack(Reliable, window=window, timeout=100, persist=True)
    r2 = u2.stack(Reliable, timeout=100)
    u1 = r1.stack(Logger, txt="U1")
    u2 = r2.stack(Logger, txt="U2")
    u1 = u1.stack(Xmit, 0, done1)
    u2 = u2.stack(Recv, 1, done2)

    async with TaskGroup() as tg:
        x1 = await tg.spawn(r1.run_p)
        tg.start_soon(l1.run)
        tg.start_soon(l2.run)

        await done1.wait()
        await done2.wait()
        await l1.aclose()
        await l2.aclose()
        x1.cancel()
    assert done_[0] == 10
    assert done_[1] == 10
