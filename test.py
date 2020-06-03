import anyio

from distmqtt.test import test_client
from asyncgpiotest import GpioWatcher

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
        return await c.set(*CFG.prefix, host,label,self.pin, value=pr, nchain=1)

    async def run(self,c,q,p):
        raise NotImplementedError("You need 'run'.")
    async def task(self,c,q,p):
        self.client = c
        self.queue = q
        self.pin = p
        await self.run()

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
        pass

class test_two(_test_in):
    pin = 2
    prep = dict(mode="count")
    async def run(self):
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
                        await q.put(m)

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

anyio.run(main, sys.argv[1] if len(sys.argv) > 1 else "gpio-mockup-A", backend="trio")
