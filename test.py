import sys
import anyio
import trio
import trio.testing

from distmqtt.test import test_client
from asyncgpio.test import GpioWatcher,Pin

from distkv_ext.gpio.task import task as GPIOtask
from distkv_ext.gpio.model import GPIOroot
from distkv_ext.gpio.config import CFG

import logging
logger = logging.getLogger(__name__)

tests = {}
def reg(nr):
    def wrap(fn):
        tests[nr] = fn
        return fn
    return reg

PinIH = Pin(False,True)
PinIL = Pin(False,False)
PinOH = Pin(True,True)
PinOL = Pin(True,False)

async def fwd_q(ts,queues):
    while True:
        msg = await ts.__anext__()
        await queues[msg.path[-1]].put(msg.value)

class _test_m(type):
    def __new__(cls, name, bases, classdict):
        result = type.__new__(cls, name, bases, classdict)
        if result.pin is not None:
            try:
                tl = tests[result.pin]
            except KeyError:
                tl = tests[result.pin] = []
            tl.append(result)
        return result

class _test(metaclass=_test_m):
    pin = None
    prep = None

    def add_prep(self,pr):
        pass
    async def prepare(self, c, host, label):
        pr = {"type":self.typ}
        pr.update(self.prep)
        self.add_prep(pr)
        for s in ("src","dest","state"):
            if s in pr:
                setattr(self,s,pr[s])
        return await c.set(*CFG.prefix, host,label,self.pin, value=pr, nchain=1)

    async def run(self,c,q,p):
        raise NotImplementedError("You need 'run'.")
    async def task(self,c,q,p):
        self.client = c
        self.queue = q
        self.pin = p
        await self.run()

    async def flushMsgs(self, *, timeout=1):
        """
        Flush the message queue, ensure that we're not getting flooded
        """
        async with anyio.move_on_after(timeout):
            while True:
                await self.queue.get()
        try:
            async with anyio.fail_after(timeout/10):
                msg = await self.queue.get()
        except TimeoutError:
            pass
        else:
            assert False, msg

    async def assertMsg(self, *data, timeout=1):
        """
        Check that the incoming messages match what we expect.
        """
        want_pins = []
        want_msgs = []
        in_pins = []
        in_msgs = []
        # Sort pin changes and DistKV messages into different bins
        # because they may interleave randomly
        for d in data:
            if isinstance(d,Pin):
                want_pins.append(d)
            else:
                want_msgs.append(d)
        try:
            while True:
                async with anyio.fail_after(timeout):
                    msg = await self.queue.get()
                    if isinstance(msg,Pin):
                        in_pins.append(msg)
                        if len(in_pins) > len(want_pins):
                            # protect against getting flooded
                            break
                    else:
                        in_msgs.append(msg)
                        if len(in_msgs) > len(want_msgs):
                            # protect against getting flooded
                            break
        except TimeoutError:
            pass
        assert in_msgs == want_msgs, (in_msgs,want_msgs)
        assert in_pins == want_pins, (in_pins,want_pins)

class _test_in(_test):
    typ = "input"
    def add_prep(self,pr):
        super().add_prep(pr)
        pr['dest'] = ("test","state",self.pin)

class _test_out(_test):
    typ = "output"
    def add_prep(self,pr):
        super().add_prep(pr)
        pr['src'] = ("test","gpio",self.pin)
        pr['state'] = ("test","state",self.pin)

class test_one(_test_in):
    pin = 1
    prep = dict(mode="read")
    async def run(self):
        self.pin.set(False)
        await self.flushMsgs()

        await self.assertMsg()
        self.pin.set(False)
        await self.assertMsg(False)
        self.pin.set(True)
        await self.assertMsg(PinIH, True)
        self.pin.set(False)
        await self.assertMsg(PinIL, False)
        self.pin.set(False)
        await self.assertMsg(False)
        await self.assertMsg()
        pass

class test_one_uniq(_test_in):
    pin = 1
    prep = dict(mode="read", change=True)
    async def run(self):
        self.pin.set(False)
        await self.flushMsgs()

        await self.assertMsg()
        self.pin.set(False)
        await self.assertMsg()
        self.pin.set(True)
        await self.assertMsg(PinIH, True)
        self.pin.set(True)
        await self.assertMsg()
        self.pin.set(False)
        await self.assertMsg(PinIL, False)
        self.pin.set(False)
        await self.assertMsg()
        pass

class test_two(_test_in):
    pin = 2
    prep = dict(mode="count",interval=3,count=None)
    async def run(self):
        self.pin.set(False)
        await self.flushMsgs()

        await self.assertMsg()
        await self.client.set(*self.dest, value=0)
        await self.assertMsg(0)
        self.pin.set(True)
        await self.assertMsg(PinIH, 1, timeout=0.3)
        await self.assertMsg(timeout=0.3)
        self.pin.set(False)
        await self.assertMsg(PinIL, timeout=0.3)
        self.pin.set(True)
        await self.assertMsg(PinIH, timeout=0.3)
        self.pin.set(False)
        await self.assertMsg(PinIL, timeout=0.3)
        await self.assertMsg(4, timeout=2)
        await self.assertMsg(timeout=5)
        self.pin.set(True)
        await self.assertMsg(PinIH, 5, timeout=0.3)
        await self.assertMsg(timeout=5)
        pass

class test_two_up(_test_in):
    pin = 2
    prep = dict(mode="count",interval=3,count=True)
    async def run(self):
        self.pin.set(False)
        await self.flushMsgs()

        await self.assertMsg()
        await self.client.set(*self.dest, value=0)
        await self.assertMsg(0)
        self.pin.set(True)
        await anyio.sleep(2)
        await self.assertMsg(PinIH, 1, timeout=0.3)
        await self.assertMsg(timeout=0.3)
        self.pin.set(False)
        await self.assertMsg(PinIL, timeout=0.3)
        self.pin.set(True)
        await self.assertMsg(PinIH, timeout=0.3)
        self.pin.set(False)
        await self.assertMsg(PinIL, timeout=0.3)
        await self.assertMsg(2, timeout=2)
        await self.assertMsg(timeout=5)
        pass

class test_three(_test_in):
    pin = 3
    prep = dict(mode="button")
    async def run(self):
        pass

class test_four(_test_out):
    pin = 4
    prep = dict(mode="write")
    async def run(self):
        pass

class test_five(_test_out):
    pin = 5
    prep = dict(mode="oneshot",t_on=1)
    async def run(self):
        pass

class test_six(_test_out):
    pin = 6
    prep = dict(mode="pulse",t_on=1,t_off=3)
    async def run(self):
        pass

async def main(label="gpio-mockup-A", host="HosT"):
    logging.basicConfig(level=logging.DEBUG)

    async with test_client() as c, \
            GpioWatcher().run() as w, \
            c.watch("test","state") as ts:
        ts = ts.__aiter__()  # currently a NOP but you never know
        server = await GPIOroot.as_handler(c)
        await server.wait_loaded()

        controller = server.follow(host,label, create=None)

        async with anyio.create_task_group() as tg:
            evt = anyio.create_event()
            await tg.spawn(GPIOtask, c, {"gpio":CFG}, controller, evt)
            await evt.wait()

            try:
                while True:
                    async with anyio.fail_after(1):
                        msg = await ts.__anext__()
                        print("init",msg)
            except TimeoutError:
                pass
            await anyio.sleep(1)

            async def watcher(q,p):
                # Monitor changes of the pin and forward them to the queue
                async with p.watch() as pq:
                    async for m in pq:
                        await q.put(Pin(*m))

            async def runner(tl,c,q,p):
                # run all tests in TL
                async with anyio.create_task_group() as tj:
                    await tj.spawn(watcher,q,p)
                    for t in tl:
                        if isinstance(t,type):
                            t = t()
                        res = await t.prepare(c,host,label)
                        await server.wait_chain(res.chain)
                        await t.task(c,q,p)
                    await tj.cancel_scope.cancel()

            async with anyio.create_task_group() as tt:
                queues = {}
                for nr in tests:
                    queues[nr] = anyio.create_queue(10)
                await tg.spawn(fwd_q,ts,queues)
                for nr,tl in tests.items():
                    await tt.spawn(runner,tl,c,queues[nr],w.pin(label, nr))
            # we come here when all tests have finished
            await tg.cancel_scope.cancel()

            pass # wait for TG end

        found=0
        for err in server.err.all_errors():
            if err.resolved:
                continue
            found += 1
            logger.error("Err %s",
                    " ".join(str(x) for x in err.path),
                    )
            for e in err:
                logger.error("%s: %r", e.comment,e.data)
        assert found==0

        pass # wait for shutdown

clock = trio.testing.MockClock(rate=8,autojump_threshold=0.2)
trio.run(main, sys.argv[1] if len(sys.argv) > 1 else "gpio-mockup-A", clock=clock)

