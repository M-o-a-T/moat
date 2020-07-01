import sys
import anyio
import trio
import trio.testing

from distmqtt.test import test_client
from asyncgpio.test import GpioWatcher, Pin

from distkv_ext.gpio.task import task as GPIOtask
from distkv_ext.gpio.model import GPIOroot
from distkv_ext.gpio.config import CFG
from distkv.util import Path

import logging

logger = logging.getLogger(__name__)

PinIH = Pin(False, True)
PinIL = Pin(False, False)
PinOH = Pin(True, True)
PinOL = Pin(True, False)


async def fwd_q(ts, queues):
    while True:
        msg = await ts.__anext__()
        await queues[msg.path[-1]].put(msg.value)


tests = {}
only = ()
# only = ("test_four","test_four_only",)
# only = ("test_three_bounce_only",)


class _test_m(type):
    def __new__(cls, name, bases, classdict):
        result = type.__new__(cls, name, bases, classdict)
        if result.pin is None:
            return result
        if only and name not in only:
            return result
        try:
            tl = tests[result.pin]
        except KeyError:
            tl = tests[result.pin] = []
        tl.append(result)
        return result


class _test(metaclass=_test_m):
    client = None
    queue = None
    pin = None
    prep = None
    typ = None  # overridden

    def add_prep(self, pr):
        pass

    async def prepare(self, c, host, label):
        pr = {"type": self.typ}
        pr.update(self.prep)
        self.add_prep(pr)
        for s in ("src", "dest", "state"):
            if s in pr:
                setattr(self, s, pr[s])
        return await c.set(CFG.prefix + (host, label, self.pin), value=pr, nchain=1)

    async def task(self, c, q, p):
        self.client = c
        self.queue = q
        self.pin = p
        await self.run()  # pylint: disable=no-member

    async def flushMsgs(self, *, timeout=1):
        """
        Flush the message queue, ensure that we're not getting flooded
        """
        async with anyio.move_on_after(timeout):
            while True:
                await self.queue.get()
        try:
            async with anyio.fail_after(timeout / 10):
                msg = await self.queue.get()
        except TimeoutError:
            pass
        else:
            assert False, msg

    async def assertMsg(self, *data, timeout=1, pick=None):
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
            if isinstance(d, Pin):
                want_pins.append(d)
            else:
                want_msgs.append(d)
        try:
            while True:
                async with anyio.fail_after(timeout):
                    msg = await self.queue.get()
                    if isinstance(msg, Pin):
                        in_pins.append(msg)
                        if len(in_pins) > len(want_pins):
                            # protect against getting flooded
                            break
                    else:
                        if pick:
                            try:
                                msg = msg[pick]
                            except KeyError:
                                raise KeyError((msg, set)) from None
                        in_msgs.append(msg)
                        if len(in_msgs) > len(want_msgs):
                            # protect against getting flooded
                            break
        except TimeoutError:
            pass
        assert in_msgs == want_msgs, (in_msgs, want_msgs)
        assert in_pins == want_pins, (in_pins, want_pins)


class _test_in(_test):
    typ = "input"
    dest = None  # prep

    def add_prep(self, pr):
        super().add_prep(pr)
        pr["dest"] = ("test", "state", self.pin)


class _test_out(_test):
    typ = "output"
    src = None  # prep
    state = None  # prep

    def add_prep(self, pr):
        super().add_prep(pr)
        pr["src"] = ("test", "gpio", self.pin)
        pr["state"] = ("test", "state", self.pin)

    async def set_src(self, value):
        await self.client.set(self.src, value=value)


class test_one(_test_in):
    pin = 1
    prep = dict(mode="read")

    async def run(self):
        self.pin.set(False)
        await self.flushMsgs()

        await self.assertMsg()
        self.pin.set(False)
        await self.assertMsg()
        self.pin.set(True)
        await self.assertMsg(PinIH, True)
        self.pin.set(False)
        await self.assertMsg(PinIL, False)
        self.pin.set(False)
        await self.assertMsg()


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
        await self.assertMsg(PinIL)
        self.pin.set(False)
        await self.assertMsg()


class test_two(_test_in):
    pin = 2
    prep = dict(mode="count", interval=3, count=None)

    async def run(self):
        self.pin.set(False)
        await self.flushMsgs()

        await self.assertMsg()
        await self.client.set(self.dest, value=0)
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


class test_two_up(_test_in):
    pin = 2
    prep = dict(mode="count", interval=3, count=True)

    async def run(self):
        self.pin.set(False)
        await self.flushMsgs()

        await self.assertMsg()
        await self.client.set(self.dest, value=0)
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
        await self.assertMsg(2, timeout=5)
        await self.assertMsg(timeout=5)


class test_three(_test_in):
    pin = 3
    prep = dict(mode="button", t_idle=1, t_bounce=0.1)

    async def run(self):
        self.pin.set(False)
        await self.flushMsgs(timeout=1.2)

        await self.assertMsg()
        await self.client.set(self.dest, value=None)
        await self.assertMsg(None)

        self.pin.set(True)
        await self.assertMsg(PinIH, timeout=0.4)
        self.pin.set(False)
        await self.assertMsg(PinIL, timeout=0.9)
        await self.assertMsg((4, 0), timeout=0.5, pick="seq")
        await self.assertMsg()


class test_three_bounce(_test_in):
    pin = 3
    prep = dict(mode="button", t_idle=1, t_bounce=0.2)

    async def run(self):
        self.pin.set(False)
        await self.flushMsgs(timeout=1.2)

        await self.assertMsg()
        await self.client.set(self.dest, value=None)
        await self.assertMsg(None)

        self.pin.set(True)
        for _ in range(3):
            await self.assertMsg(PinIH, timeout=0.15)
            self.pin.set(False)
            await self.assertMsg(PinIL, timeout=0.15)
            self.pin.set(True)
        await self.assertMsg(PinIH, timeout=0.35)
        self.pin.set(False)
        for _ in range(3):
            await self.assertMsg(PinIL, timeout=0.15)
            self.pin.set(True)
            await self.assertMsg(PinIH, timeout=0.15)
            self.pin.set(False)
        await self.assertMsg(PinIL, timeout=0.9)
        await self.assertMsg((6, 0), timeout=0.3, pick="seq")


class test_three_bounce_only(_test_in):
    pin = 3
    prep = dict(mode="button", t_idle=1, t_bounce=0.2)

    async def run(self):
        self.pin.set(False)
        await self.flushMsgs(timeout=1.2)

        await self.assertMsg()
        await self.client.set(self.dest, value=None)
        await self.assertMsg(None)

        for _ in range(6):
            self.pin.set(True)
            await self.assertMsg(PinIH, timeout=0.15)
            self.pin.set(False)
            await self.assertMsg(PinIL, timeout=0.15)
        await self.assertMsg(timeout=2)


class test_three_bounce_skip(_test_in):
    pin = 3
    prep = dict(mode="button", t_idle=1, t_bounce=0.2, skip=False)

    async def run(self):
        self.pin.set(False)
        await self.flushMsgs(timeout=1.2)

        await self.assertMsg()
        await self.client.set(self.dest, value=None)
        await self.assertMsg(None)

        for _ in range(6):
            self.pin.set(True)
            await self.assertMsg(PinIH, timeout=0.15)
            self.pin.set(False)
            await self.assertMsg(PinIL, timeout=0.15)
        await self.assertMsg((8, 0), timeout=2, pick="seq")


class test_four(_test_out):
    pin = 4
    prep = dict(mode="write")

    async def run(self):
        await self.set_src(False)
        await self.flushMsgs()

        await self.set_src(True)
        await self.assertMsg(PinOH, True)
        await self.set_src(True)
        await self.assertMsg(True)
        await self.set_src(False)
        await self.assertMsg(PinOL, False)
        await self.set_src(False)
        await self.assertMsg(False)


class test_four_only(_test_out):
    pin = 4
    prep = dict(mode="write", change=True)

    async def run(self):
        await self.set_src(False)
        await self.flushMsgs()

        await self.set_src(True)
        await self.assertMsg(PinOH, True)

        await self.client.set(self.state, value=None)
        await self.assertMsg(None)

        await self.set_src(False)
        await self.assertMsg(PinOL)
        await self.set_src(False)
        await self.assertMsg()
        await self.set_src(True)
        await self.assertMsg(PinOH, True)
        await self.set_src(False)
        await self.assertMsg(PinOL)


class test_five(_test_out):
    pin = 5
    prep = dict(mode="oneshot", t_on=1)

    async def run(self):
        await self.set_src(False)
        await self.flushMsgs()

        await self.set_src(True)
        await self.assertMsg(PinOH, True, timeout=0.4)
        await self.assertMsg(timeout=0.3)
        await self.assertMsg(PinOL, False)
        await self.set_src(False)
        await self.assertMsg()

        await self.set_src(True)
        await self.assertMsg(PinOH, True, timeout=0.3)
        await self.set_src(False)
        await self.assertMsg(PinOL, False, timeout=0.3)
        await self.assertMsg()


class test_six(_test_out):
    pin = 6
    prep = dict(mode="pulse", t_on=1, t_off=3)

    async def run(self):
        await self.set_src(False)
        await self.flushMsgs()

        await self.set_src(True)
        await self.assertMsg(PinOH, 0.25, timeout=0.4)
        await self.assertMsg(timeout=0.4)
        await self.assertMsg(PinOL, timeout=0.4)
        await self.set_src(False)
        await self.assertMsg(False, timeout=0.2)
        await self.assertMsg()

        await self.set_src(True)
        await self.assertMsg(PinOH, 0.25, timeout=0.3)
        await self.set_src(False)
        await self.assertMsg(PinOL, False, timeout=0.3)
        await self.assertMsg()

        await self.set_src(True)
        await self.assertMsg(PinOH, 0.25, timeout=0.4)
        for _ in range(3):
            await self.assertMsg(timeout=0.3)
            await self.assertMsg(PinOL, timeout=0.5)
            await self.assertMsg(timeout=2.3)
            await self.assertMsg(PinOH, timeout=0.5)
        await self.set_src(False)
        await self.assertMsg(PinOL, False, timeout=0.3)
        await self.assertMsg()


async def main(label="gpio-mockup-A", host="HosT"):
    logging.basicConfig(level=logging.DEBUG, format="%(relativeCreated)d %(name)s %(message)s")

    async with test_client() as c, GpioWatcher(interval=0.05).run() as w, c.watch(
        Path("test","state")
    ) as ts:
        ts = ts.__aiter__()  # currently a NOP but you never know
        server = await GPIOroot.as_handler(c)
        await server.wait_loaded()

        controller = server.follow(Path(host, label), create=None)

        async with anyio.create_task_group() as tg:
            evt = anyio.create_event()
            await tg.spawn(GPIOtask, controller, evt)
            await evt.wait()

            try:
                while True:
                    async with anyio.fail_after(1):
                        msg = await ts.__anext__()
                        print("init", msg)
            except TimeoutError:
                pass
            await anyio.sleep(1)

            async def watcher(q, p):
                # Monitor changes of the pin and forward them to the queue
                async with p.watch() as pq:
                    async for m in pq:
                        await q.put(Pin(*m))

            async def runner(tl, c, q, p):
                # run all tests in TL
                async with anyio.create_task_group() as tj:
                    await tj.spawn(watcher, q, p)
                    for t in tl:
                        if isinstance(t, type):
                            t = t()
                        res = await t.prepare(c, host, label)
                        await server.wait_chain(res.chain)
                        await t.task(c, q, p)
                    await tj.cancel_scope.cancel()

            async with anyio.create_task_group() as tt:
                queues = {}
                for nr in tests:
                    queues[nr] = anyio.create_queue(10)
                await tg.spawn(fwd_q, ts, queues)
                for nr, tl in tests.items():
                    await tt.spawn(runner, tl, c, queues[nr], w.pin(label, nr))
            # we come here when all tests have finished
            await tg.cancel_scope.cancel()

            pass  # wait for TG end

        found = 0
        for err in server.err.all_errors():
            if err.resolved:
                continue
            found += 1
            logger.error(
                "Err %s", " ".join(str(x) for x in err.path),
            )
            for e in err:
                logger.error("%s: %r", e.comment, e.data)
        assert found == 0

        pass  # wait for shutdown


# clock = trio.testing.MockClock(rate=1.5,autojump_threshold=0.2)
trio.run(main, sys.argv[1] if len(sys.argv) > 1 else "gpio-mockup-A")  # , clock=clock)
