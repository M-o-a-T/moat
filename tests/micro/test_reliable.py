"""
Test reliable retransmission, using various parameters.
"""

from __future__ import annotations

import os
import pytest

from moat.micro._test import Loopback
from moat.micro.compat import Event, TaskGroup
from moat.micro.proto.reliable import ReliableMsg, EphemeralMsg
from moat.micro.proto.stack import StackedMsg, LogMsg

pytestmark = pytest.mark.anyio

done_ = [None] * 4


class Head(StackedMsg):
    "sender/receiver test common code"

    n: int = 0
    done: Event = None

    async def setup(self):  # noqa:D102
        await super().setup()
        self.done = Event()


class Xmit(Head):
    "sending test class"

    async def run(self):
        "main"
        async with TaskGroup() as tg:
            for n in range(10):
                await tg.spawn(self.send, dict(n=n, msg="Hey"), _name="Xhey")
                self.n += 1
        self.done.set()


class XmitE(Head):
    "ephemeral sending test"

    async def run(self):
        "main"
        for n in range(3):
            await self.send(EphemeralMsg(42, dict(n=n)))
            self.n += 1
        self.done.set()


class Recv(Head):
    "receiving test class"

    async def run(self):
        "main"
        got = 0
        for _ in range(10):
            msg = await self.recv()
            got |= 1 << msg["n"]
        assert got == (2**10) - 1
        self.n = 10
        self.done.set()


class RecvE(Head):
    "receiving ephemeral messages"

    async def run(self):
        "main"
        got = 0
        while True:
            msg = await self.recv()
            got |= 1 << msg["n"]
            self.n += 1
            if msg["n"] == 2:
                break
        assert got == 1 << 2
        self.done.set()


# Zero on both sides can deadlock
@pytest.mark.parametrize("qlen1", [2, 20])
@pytest.mark.parametrize("qlen2", [2, 20])
@pytest.mark.parametrize("window", [4, 8, 20])
async def test_basic(qlen1, qlen2, window):
    "basic test for Reliable channel"
    u1 = Loopback(qlen=qlen1)
    u2 = Loopback(qlen=qlen2)
    u1.link(u2)
    u2.link(u1)
    if "TRACE" in os.environ:
        u1 = LogMsg(u1, dict(txt="L1"))
        u2 = LogMsg(u2, dict(txt="L2"))
    u1 = ReliableMsg(u1, dict(_nowait=True, retries=999, window=window, timeout=100, persist=True))
    u2 = ReliableMsg(u2, dict(_nowait=True, retries=999, timeout=100))
    if "TRACE" in os.environ:
        u1 = LogMsg(u1, dict(txt="U1"))
        u2 = LogMsg(u2, dict(txt="U2"))
    u1 = Xmit(u1, {})
    u2 = Recv(u2, {})

    async with TaskGroup() as tg, u1, u2:
        await tg.spawn(u1.run)
        await tg.spawn(u2.run)
        await u1.done.wait()
        await u2.done.wait()
    assert u1.n == 10
    assert u2.n == 10


async def test_eph():
    "basic test for Reliable channel"
    ## XXX this test is woefully incomplete

    u1 = Loopback(qlen=4)
    u2 = Loopback(qlen=4)
    u1.link(u2)
    u2.link(u1)
    if "TRACE" in os.environ:
        u1 = LogMsg(u1, dict(txt="L1"))
        u2 = LogMsg(u2, dict(txt="L2"))
    u1 = ReliableMsg(u1, dict(_nowait=True, retries=999, window=4, timeout=100, persist=True))
    u2 = ReliableMsg(u2, dict(_nowait=True, retries=999, timeout=100))
    if "TRACE" in os.environ:
        u1 = LogMsg(u1, dict(txt="U1"))
        u2 = LogMsg(u2, dict(txt="U2"))
    u1 = XmitE(u1, {})
    u2 = RecvE(u2, {})

    async with TaskGroup() as tg, u1, u2:
        await tg.spawn(u1.run)
        await tg.spawn(u2.run)
        await u1.done.wait()
        await u2.done.wait()
    assert u1.n == 3
    assert u2.n == 1


@pytest.mark.parametrize("window", [4, 8])
@pytest.mark.parametrize("loss", [0.1, 0.7])
async def test_lossy(window, loss):
    "basic test for Reliable channel"
    qlen1 = 5
    qlen2 = 5
    u1 = Loopback(qlen=qlen1, loss=loss)
    u2 = Loopback(qlen=qlen2, loss=loss)
    u1.link(u2)
    u2.link(u1)
    if "TRACE" in os.environ:
        u1 = LogMsg(u1, dict(txt="L1"))
        u2 = LogMsg(u2, dict(txt="L2"))
    u1 = ReliableMsg(u1, dict(_nowait=True, retries=999, window=window, timeout=100, persist=True))
    u2 = ReliableMsg(u2, dict(_nowait=True, retries=999, timeout=100))
    if "TRACE" in os.environ:
        u1 = LogMsg(u1, dict(txt="U1"))
        u2 = LogMsg(u2, dict(txt="U2"))
    u1 = Xmit(u1, {})
    u2 = Recv(u2, {})

    async with TaskGroup() as tg, u1, u2:
        await tg.spawn(u1.run)
        await tg.spawn(u2.run)
        await u1.done.wait()
        await u2.done.wait()
    assert u1.n == 10
    assert u2.n == 10
