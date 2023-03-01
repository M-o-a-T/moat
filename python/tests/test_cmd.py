# test CMD processing
import pytest

from moat.cmd import Base,Request,Logger,Reliable, NotImpl, _Stacked
from moat.compat import run, CancelledError, spawn
from contextlib import asynccontextmanager
from functools import partial
from copy import deepcopy

import anyio

import random
rand = random.Random()
LOG=False

class Pinger(Base):
    seen = 0
    def _init(self,lim,evt):
        self.lim = lim
        self.evt = evt

    async def cmd_pi(self,a,i):
        assert not self.seen & (1<<i)
        self.seen |= 1<<i
        return f"po:{i}"

    async def ping(self, i):
        assert not self.seen & (1<<i)
        self.seen |= 1<<i
        try:
            res = await self.parent.send("pi",i)
        except CancelledError:
            return
        assert res == f"po:{i}"
        if self.seen == (1<<self.lim)-1:
            #print("Done",self.lim,self.seen)
            self.evt.set()

async def lg(p,*a,**k):
    #print("ST",p,a,k)
    try:
        res = await p(*a,**k)
    except Exception as exc:
        #print("XX",exc,p,a,k)
        raise
    else:
        #print("OK",res,p,a,k)
        return res

class Router(_Stacked):
    child = NotImpl
    def __init__(self, other=None, fail=0, min_dly=0, max_dly=0):
        self.fail = fail
        self.min_dly = min_dly
        self.max_dly = max_dly
        self.qw,self.qr = anyio.create_memory_object_stream(99999)

        if other is not None:
            self.other = other
            other.other = self

    async def open(self):
        self.fwd_task = await spawn(None, self.fwd)
        await self.child.open()

    async def close(self):
        self.fwd_task.cancel()
        await self.child.close()

    async def delay(self):
        if not self.max_dly:
            return
        await anyio.sleep(rand.uniform(self.min_dly,self.max_dly)/1000)

    async def fwd(self):
        while True:
            msg = await self.qr.receive()
            if rand.uniform(0,1) <= self.fail:
                continue
            await self.delay()
            await self.other.child.dispatch(deepcopy(msg))

    async def send(self,msg):
        await self.qw.send(msg)

    def spawn(self, p,*a,_name=None,**k):
        self.tg.start_soon(partial(lg,p,*a,**k))

    @asynccontextmanager
    async def main(self):
        async with anyio.create_task_group() as tg:
            self.tg = tg
            yield tg
            await self.child.close()


async def _test_basic(erange,fail,delay1,delay2,tx,window):
    evt1 = anyio.Event()
    evt2 = anyio.Event()

    d1 = Router(fail=fail,min_dly=delay1/10,max_dly=delay1)
    d2 = Router(d1,min_dly=delay2/10,max_dly=delay2)

    async with d1.main(),d2.main():
        if LOG:
            l1 = d1.stack(Logger,"U1")
            l2 = d2.stack(Logger,"U2")
        else:
            l1=d1
            l2=d2

        r1 = l1.stack(Reliable,timeout=50+tx,window=window)
        r2 = l2.stack(Reliable,timeout=50,window=window*2)

        if LOG:
            L1 = r1.stack(Logger,"M1")
            L2 = r2.stack(Logger,"M2")
        else:
            L1=r1
            L2=r2

        q1 = L1.stack(Request)
        q2 = L2.stack(Request)

        p1 = q1.stack(Pinger,erange,evt1)
        p2 = q2.stack(Pinger,erange,evt2)

        async with anyio.create_task_group() as tg:
            tg.start_soon(d1.open)
            tg.start_soon(d2.open)

        for x in range(erange):
            if x & 1:
                d2.tg.start_soon(p2.ping,x)
            else:
                d1.tg.start_soon(p1.ping,x)
        with anyio.move_on_after(10):
            await evt1.wait()
            await evt2.wait()

        async with anyio.create_task_group() as tg:
            tg.start_soon(d1.close)
            tg.start_soon(d2.close)

    assert p1.seen
    assert p2.seen == p1.seen

@pytest.mark.parametrize("erange",(2,10))
@pytest.mark.parametrize("fail",(0,0.2,0.6))
@pytest.mark.parametrize("delay1",(0,10))
@pytest.mark.parametrize("delay2",(0,20))
@pytest.mark.parametrize("tx",(0,10))
@pytest.mark.parametrize("window",(4,8,128))
def test_basic(erange,fail,delay1,delay2,tx,window, autojump_clock):
    run(_test_basic, erange=erange,fail=fail,delay1=delay1,delay2=delay2,tx=tx,window=window)
