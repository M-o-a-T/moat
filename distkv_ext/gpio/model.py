"""
DistKV client data model for GPIO
"""
import anyio
from anyio.exceptions import ClosedResourceError

from distkv.obj import ClientEntry, ClientRoot
from distkv.util import combine_dict, PathLongener
from distkv.errors import ErrorRoot
from distkv.exceptions import ServerError
from collections import Mapping
import asyncgpio as gpio

import logging
logger = logging.getLogger(__name__)
        
def _DIR(d):
    if d is None:
        return gpio.REQUEST_EVENT_BOTH_EDGES
    if d:
        return gpio.REQUEST_EVENT_RISING_EDGE
    else:
        return gpio.REQUEST_EVENT_FALLING_EDGE

class _GPIObase(ClientEntry):
    """
    Forward ``_update_chip`` calls to child entries.
    """
    _chip = None

    @property
    def chip(self):
        if self._chip is None:
            self._chip = self.parent.chip
        return self._chip

    async def set_value(self, val):
        await super().set_value(val)
        if self.chip is not None:
            await self._update_chip()

    async def update_chip(self):
        await self.parent.update_chip()

    async def _update_chip(self):
        if not self.val_d(True,'present'):
            return
        await self.setup()
        for k in self:
            await k._update_chip()

    async def setup(self):
        pass

class _GPIOnode(_GPIObase):
    """
    Base class for a single input or output.
    """
    _poll = None

    @property
    def card(self):
        return self._path[-2]

    @property
    def port(self):
        return self._path[-1]

    @property
    def task_group(self):
        return self.parent.task_group

    async def setup(self):
        await super().setup()
        if self.chip is None:
            self._poll = None
            return

        if self._poll is not None:
            await self._poll.cancel()
            self._poll = None

        pass


class GPIOline(_GPIOnode):
    """Describes one GPIO line.
    """
    _work = None

    async def setup(self):
        await super().setup()
        if self.chip is None:
            return
        if self._work:
            await self._work.aclose()

        try:
            typ = self.find_cfg('type')
        except KeyError:
            typ = "NOT_SET"
        if typ == "input":
            await self._setup_input()
        elif typ == "output":
            await self._setup_output()
        else:
            await self.root.err.record_error("gpio", *self.subpath, comment="Line type not set", data={"path":self.subpath,"typ":typ})

    # Input #

    async def _poll_task(self, evt, dest):
        negate = self.find_cfg('low')

        async with anyio.open_cancel_scope() as sc:
            self._poll = sc
            wire = self.chip.line(self._path[-1])
            with wire.monitor(gpio.REQUEST_EVENT_BOTH_EDGES) as mon:
                await evt.set()
                async for e in mon:
                    await self.client.set(*dest, value=(e.value != negate))
                    await self.root.err.record_working("gpio", *self.subpath)

    async def _button_task(self, evt, dest):
        negate = self.find_cfg('low')
        skip = self.find_cfg('skip')
        bounce = self.find_cfg('t_bounce')
        idle = self.find_cfg('t_idle')
        idle2 = self.find_cfg('t_clear')
        count = self.find_cfg('count')

        logger.debug("bounce %s idle %s count %s", bounce,idle,count)
        async with anyio.open_cancel_scope() as sc:
            self._poll = sc

            wire = self.chip.line(self._path[-1])
            with wire.monitor(gpio.REQUEST_EVENT_BOTH_EDGES) as mon:
                await evt.set()
                i = mon.__aiter__()

                def td(a,b):
                    a=a.timestamp
                    b=b.timestamp
                    return a[0]-b[0]+(a[1]-b[1])/1000000000
                def ts(a):
                    a = a.timestamp
                    return "%03d.%03d" % (a[0]%1000, a[1]/1000000)

                def inv(x):
                    nonlocal negate

                    if x is None:
                        return x
                    if negate:
                        return not x
                    else:
                        return bool(x)

                # inverting the conditions (and the results, below) is less work
                # than inverting the input values
                count = inv(count)

                async def record(e1):
                    # We record a single sequence of possibly-dirty signals.
                    # e0/e1: first+last change of a sequence with change intervals
                    #        shorter than `bounce`
                    # e2: first change after that sequence, or None when timed out.
                    # 
                    res = []
                    e0 = e1
                    ival=e0.value
                    logger.debug("Start %s %s",e1.value,ts(e1))
                    while True:
                        # wait for signal change
                        try:
                            async with anyio.fail_after(idle):
                                e2 = await mon.__anext__()
                                logger.debug("See %s %s",e2.value,ts(e2))
                        except TimeoutError:
                            e2 = None
                            e1x = e1
                        else:
                            # it bounced, so continue
                            if td(e2,e1) < bounce:
                                e1=e2
                                continue

                        if td(e1,e0) > bounce and e1.value != e0.value:
                            # e0>e1 ends up where it started from, thus we have a dirty signal.
                            # TODO add a flag to ignore it
                            if skip:
                                e1 = e0
                            else:
                                # logic see below
                                if count is not bool(e1.value):
                                    res.append(int(td(e1,e0)/bounce))
                                e0 = e1

                        if e2 is None:
                            logger.debug("Done: %s %s",ival,res)
                            return not ival,res,inv(e1x.value)

                        # if count is None, count
                        # if count is e1.value, don't
                        if count is not bool(e2.value):
                            res.append(int(td(e2,e0)/bounce))
                        e0 = e1 = e2
                        
                clear = True
                while True:
                    if clear and idle2:
                        try:
                            async with anyio.fail_after(idle2):
                                e = await mon.__anext__()
                        except TimeoutError:
                            await self.client.set(*dest, value=None)
                            clear = False
                            continue
                    else:
                        e = await mon.__anext__()
                    ival,res,oval = await record(e)
                    if not res:
                        continue

                    await self.client.set(*dest, value={"start":ival,"seq":res,"end":oval,"t":bounce})
                    await self.root.err.record_working("gpio", *self.subpath)
                    clear = True

    async def _count_task(self, evt, dest):
        intv = self.find_cfg('interval')
        direc = self.find_cfg('count')

        async with anyio.open_cancel_scope() as sc:
            self._poll = sc

            async def get_value():
                val = await self.client.get(*dest, nchain=2)
                ch={}
                if 'value' in val:
                    ch['chain'] = val.chain

                val = val.get('value', 0)
                if not isinstance(val, (int,float)):
                    val = 0
                return val,ch

            async def set_value():
                nonlocal d,ch,val,t
                t = await anyio.current_time()
                try:
                    res = await self.client.set(*dest, value=val+d, nchain=2, **ch)
                    ch['chain'] = res.chain
                except ServerError as exc:
                    # Somebody else changed my value? Retry once.
                    await self.root.err.record_error("gpio", *self.subpath, comment="Server error", data={"path":self.subpath, "value":val, **ch}, exc=exc)

                    val,ch = await get_value()
                    res = await self.client.set(*dest, value=val+d, nchain=2, **ch)
                ch['chain'] = res.chain
                await self.root.err.record_working("gpio", *self.subpath)
                val += d
                d = 0

            val,ch = await get_value()

            wire = self.chip.line(self._path[-1])
            with wire.monitor(_DIR(direc)) as mon:
                await evt.set()
                i = mon.__aiter__()
                t = await anyio.current_time()
                d = None
                # The idea here is that when d is None, nothing is happening, thus we don't wait.
                # Otherwise we set the value at the first change, then every `intv` seconds.
                while True:
                    if d is None:
                        logger.debug("wait indefinitely in %s", self.subpath)
                        e = await i.__anext__()
                        d = 1
                        await set_value()
                        assert d==0
                    tm = t + intv - await anyio.current_time()
                    if tm > 0:
                        logger.debug("wait for %s in %s", tm, self.subpath)
                        try:
                            async with anyio.fail_after(tm):
                                e = await i.__anext__()
                        except TimeoutError:
                            # Nothing happened before the timeout.
                            if d == 0:
                                d = None
                                # Nothing continues to happen. Skip sending.
                                continue
                        else:
                            d += 1
                            continue
                    await set_value()



    async def _setup_input(self):
        try:
            mode = self.find_cfg('mode')
            dest = self.find_cfg('dest')
        except KeyError:
            await self.root.err.record_error("gpio", *self.subpath, comment="mode or dest not set", data={"path":self.subpath}, exc=exc)
            return

        evt = anyio.create_event()
        if mode == "read":
            await self.task_group.spawn(self._poll_task, evt, dest)
        elif mode == "count":
            # These two are in the global config and thus can't raise KeyError
            await self.task_group.spawn(self._count_task, evt, dest)
        elif mode == "button":
            # These two are in the global config and thus can't raise KeyError
            await self.task_group.spawn(self._button_task, evt, dest)
        else:
            await self.root.err.record_error("gpio", *self.subpath, comment="mode unknown", data={"path":self.subpath, "mode":mode})
            return
        await evt.wait()

    # Output #

    async def with_output(self, evt, src, proc, *args):
        """
        Task that monitors one entry and writes its value to the GPIO controller.

        Also the value is mirrored to ``cur`` if that's set.

        `proc` is called with the GPIO line, the current value from DistKV,
        and the remaining arguments as given.
        """
        async with anyio.open_cancel_scope() as sc:
            self._poll = sc
            with self.chip.line(self._path[-1]).open(direction=gpio.DIRECTION_OUTPUT) as line:
                async with self.client.watch(*src, min_depth=0, max_depth=0, fetch=True) as wp:
                    pl=PathLongener()
                    old_val = None
                    await evt.set()
                    async for msg in wp:
                        pl(msg)
                        try:
                            val = msg.value
                        except AttributeError:
                            if msg.get("state","") != "uptodate":
                                await self.root.err.record_error("gpio", *self.subpath, comment="Missing value in msg", data={"path":self.subpath,"msg":msg})
                            continue

                        if val in (False,True,0,1):
                            val = bool(val)
                            if old_val is val:
                                continue
                            old_val = val
                            try:
                                await proc(line, val, *args)
                            except StopAsyncIteration:
                                await self.root.err.record_error("gpio", *self.subpath, data={'value': val}, comment="Stopped due to bad timer value")
                                return
                            except Exception as exc:
                                await self.root.err.record_error("gpio", *self.subpath, data={'value': val}, exc=exc)
                            else:
                                await self.root.err.record_working("gpio", *self.subpath)
                        else:
                            await self.root.err.record_error("gpio", *self.subpath, comment="Bad value: %r" % (val,))

    async def _set_value(self, line, val, state, negate):
        """
        Task that monitors one entry and writes its value to the GPIO controller.

        Also the value is mirrored to ``cur`` if that's set.
        """
        if line is not None:
            logger.debug("Setting %s to %s",line,value)
            line.value = val != negate
        if state is not None:
            await self.client.set(*state, value=val)

    async def _oneshot_value(self, line, val, state, negate, t_on):
        """
        Task that monitors one entry. Its value is written to the
        controller but if it's = ``direc`` it's reverted autonomously after
        ``intv`` seconds. The current state is written to ``cur``, if
        present.

        ``t_on`` may be a number or a path, if the latter
        it's read from DistKV. ``state`` must be a path.

        """

        async def work_oneshot(evt):
            nonlocal t_on
            if isinstance(t_on, (list,tuple)):
                t_on = (await self.client.get(*t_on)).value_or(None)
            async with anyio.open_cancel_scope() as sc:
                try:
                    self._work = sc
                    self._work_done = anyio.create_event()
                    try:
                        await self._set_value(line,True,state,negate)
                        await evt.set()
                        if state is not None:
                            await self.client.set(*state, value=True)
                        await anyio.sleep(t_on)

                    finally:
                        async with anyio.fail_after(2, shield=True):
                            await self._set_value(line,False,state,negate)
                finally:
                    if self._work is sc:
                        await self._work_done.set()
                        self._work = None
                        self._work_done = None

        if val:
            evt = anyio.create_event()
            await self.task_group.spawn(work_oneshot, evt)
            await evt.wait()
        else:
            if self._work:
                await self._work.cancel()
                await self._work_done.wait()
            else:
                await self._set_value(None, False, state, negate)

    async def _pulse_value(self, line, val, state, negate, t_on, t_off):
        """
        Pulse the value.

        The state records the cycle ratio.
        """
        async def work_pulse(evt):
            nonlocal t_on
            nonlocal t_off
            if isinstance(t_on, (list,tuple)):
                t_on = (await self.client.get(*t_on)).value_or(None)
            if isinstance(t_off, (list,tuple)):
                t_off = (await self.client.get(*t_off)).value_or(None)
            if t_on is None or t_off is None:
                raise StopAsyncIteration

            try:
                async with anyio.open_cancel_scope() as sc:
                    self._work = sc
                    self._work_done = anyio.create_event()
                    await evt.set()
                    if state is not None:
                        await self.client.set(*state, value=t_on/(t_on+t_off))
                    while True:
                        line.value = not negate
                        await anyio.sleep(t_on)
                        line.value = negate
                        await anyio.sleep(t_off)
            finally:
                if self._work is sc:
                    await self._work_done.set()
                    self._work = None
                    self._work_done = None

                async with anyio.fail_after(2, shield=True):
                    if state is not None:
                        try:
                            val = line.value
                        except ClosedResourceError:
                            pass
                        else:
                            await self.client.set(*state, value=(val != negate))

        if val:
            evt = anyio.create_event()
            await self.task_group.spawn(work_pulse, evt)
            await evt.wait()
        else:
            if self._work:
                await self._work.cancel()
                await self._work_done.wait()
            else:
                await self._set_value(None, False, state, negate)


    async def _setup_output(self):

        try:
            mode = self.find_cfg('mode')
            src = self.find_cfg('src')
        except KeyError:
            logger.info("mode or src not set in %s",self.subpath)
            return

        # Rest state. The input value in DistKV is always active=high.
        negate = self.find_cfg('low')
        t_on = self.find_cfg('t_on', default=None)
        t_off = self.find_cfg('t_off', default=None)
        state = self.find_cfg('state', default=None)

        evt = anyio.create_event()
        if mode == "write":
            await self.task_group.spawn(self.with_output, evt, src, self._set_value, state, negate)
        elif mode == "oneshot":
            if t_on is None:
                await self.root.err.record_error("gpio", *self.subpath, comment="t_on not set", data={"path":self.subpath})
                return
            await self.task_group.spawn(self.with_output, evt, src, self._oneshot_value, state, negate, t_on)
        elif mode == "pulse":
            if t_on is None:
                await self.root.err.record_error("gpio", *self.subpath, comment="t_on not set", data={"path":self.subpath})
                return
            if t_off is None:
                await self.root.err.record_error("gpio", *self.subpath, comment="t_off not set", data={"path":self.subpath})
                return
            await self.task_group.spawn(self.with_output, evt, src, self._pulse_value, state, negate, t_on, t_off)
        else:
            await self.root.err.record_error("gpio", *self.subpath, comment="mode unknown", data={"path":self.subpath, "mode":mode})
            return
        await evt.wait()


class GPIOchip(_GPIObase):
    _chip = None

    @property
    def chip(self):
        return self._chip

    @property
    def name(self):
        return self._path[-1]

    @classmethod
    def child_type(cls, name):
        if not isinstance(name,int):
            return None
        return GPIOline

    async def update_chip(self):
        await self._update_chip()

    async def set_chip(self, chip):
        self._chip = chip
        await self._update_chip()

    async def set_value(self, val):
        await super().set_value(val)
        await self.update_chip()


class GPIOhost(ClientEntry):
    def child_type(self, name):
        return GPIOchip


class GPIOroot(ClientRoot):
    CFG = "gpio"
    err = None

    async def run_starting(self):
        self._chip = None
        if self.err is None:
            self.err = await ErrorRoot.as_handler(self.client)
        await super().run_starting()

    def child_type(self, name):
        return GPIOhost

