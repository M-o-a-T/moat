"""
Test reliable retransmission, using various parameters.
"""

import anyio
import pytest

from moat.micro._test import Loopback
from moat.micro.compat import TaskGroup, Event, log
from moat.micro.proto.reliable import ReliableMsg
from moat.micro.proto.stack import LogMsg, StackedMsg

pytestmark = pytest.mark.anyio

done_ = [None] * 4


class Head(StackedMsg):
    "sender/receiver test common code"

    async def setup(self):
        await super().setup()
        self.done = Event()
        self.n = 0


class Xmit(Head):
    "seniding test class"

    async def run(self):
        "main"
        async with TaskGroup() as tg:
            for n in range(10):
                await tg.spawn(self.send, dict(n=n, msg="Hey"), _name="Xhey")
                self.n += 1
        self.done.set()

    async def send(self, d):
        # log("StX %r",d)
        await super().send(d)
        # log("EtX %r",d)

class Recv(Head):
    "receiving test class"

    async def run(self):
        "main"
        got = 0
        for _ in range(10):
            msg = await self.recv()
            # log("Rcv %r", msg)
            got |= 1 << msg["n"]
        assert got == (2**10) - 1
        self.n = 10
        self.done.set()


# Zero on both sides can deadlock
@pytest.mark.parametrize("qlen1", [2, 20])
@pytest.mark.parametrize("qlen2", [2, 20])
@pytest.mark.parametrize("window", [4, 8, 20])
@pytest.mark.parametrize("loss", [0, 0.1, 0.7])
async def test_basic(qlen1, qlen2, window, loss):
    "basic test for Reliable channel"
    u1 = Loopback(qlen=qlen1, loss=loss)
    u2 = Loopback(qlen=qlen2, loss=loss)
    u1.link(u2)
    u2.link(u1)
#   u1 = LogMsg(u1, dict( txt="L1"))
#   u2 = LogMsg(u2, dict( txt="L2"))
    u1 = ReliableMsg(u1, dict(_nowait=True, retries=999, window=window, timeout=100, persist=True))
    u2 = ReliableMsg(u2, dict(_nowait=True, retries=999, timeout=100))
    u1 = LogMsg(u1, dict(txt="U1"))
    u2 = LogMsg(u2, dict(txt="U2"))
    u1 = Xmit(u1, {})
    u2 = Recv(u2, {})

    async with TaskGroup() as tg:
        async with u1,u2:
            await tg.spawn(u1.run)
            await tg.spawn(u2.run)
            await u1.done.wait()
            await u2.done.wait()
    assert u1.n == 10
    assert u2.n == 10
