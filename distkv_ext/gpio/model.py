"""
DistKV client data model for GPIO
"""
import anyio
from anyio.exceptions import ClosedResourceError

from distkv.obj import ClientEntry, ClientRoot
from distkv.util import combine_dict
from distkv.errors import ErrorRoot
from collections import Mapping

import logging
logger = logging.getLogger(__name__)
        
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
    def tg(self):
        return self.chip.task_group

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
            await self.root.err.record_error("gpio", *self.subpath, comment="Line type not set", data={"path":self.subpath,"typ":typ}, exc=exc)

    # Input #

    async def _poll_task(self, evt, dest):
        async with anyio.open_cancel_scope() as sc:
            self._poll = sc
            rest = self.find_cfg('rest', default=False)
            async with self.chip.monitor_input(self.card, self.port) as mon:
                await evt.set()
                async for val in mon:
                    await self.client.set(*dest, value=(val != rest))
                    await self.root.err.record_working("gpio", *self.subpath)

    async def _count_task(self, evt, dest, intv, direc):
        async with anyio.open_cancel_scope() as sc:
            self._poll = sc
            async def get_value():
                delta = await self.client.get(*dest, nchain=2)
                ch={}
                if 'value' in delta:
                    ch['chain'] = delta.chain

                delta = delta.data.get('value', 0)
                if not isinstance(delta, (int,float)):
                    delta = 0
                return delta,ch
            delta,ch = await get_value()

            async with self.chip.count_input(self.card, self.port, direction=direc, interval=intv) as mon:
                await evt.set()
                async for val in mon:
                    try:
                        res = await self.client.set(*dest, value=val+delta, nchain=2, **ch)
                        ch['chain'] = res.chain
                    except ServerError as exc:
                        # Somebody else changed my value? Retry once.
                        await self.root.err.record_error("gpio", *self.subpath, comment="Server error: %r" % (msg,), data={"path":self.subpath}, exc=exc)

                        delta,ch = await get_value()
                        res = await self.client.set(*dest, value=val+delta, nchain=2, **ch)
                        ch['chain'] = res.chain
                    else:
                        await self.root.err.record_working("gpio", *self.subpath)


    async def _setup_input(self):
        try:
            mode = self.find_cfg('mode')
            dest = self.find_cfg('dest')
        except KeyError:
            # logger.debug("Port not configured: %s %s %d %d", *self.subpath[-4:])
            await self.root.err.record_error("gpio", *self.subpath, comment="mode or dest not set", data={"path":self.subpath}, exc=exc)
            return

        evt = anyio.create_event()
        if mode == "read":
            await self.tg.spawn(self._poll_task, evt, dest)
        elif mode == "count":
            # These two are in the global config and thus can't raise KeyError
            intv = self.find_cfg('interval')
            direc = self.find_cfg('count')
            await self.tg.spawn(self._count_task, evt, dest, intv, direc)
        else:
            await self.root.err.record_error("gpio", *self.subpath, comment="mode unknown", data={"path":self.subpath, "mode":mode})
            return  # mode unknown
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
            with self.chip.open(self.port, direction=gpio.DIRECTION_OUTPUT) as line:
                async with self.client.watch(*src, min_depth=0, max_depth=0, fetch=True) as wp:
                    await evt.set()
                    async for msg in wp:
                        try:
                            val = msg.value
                        except AttributeError:
                            if msg.get("state","") != "uptodate":
                                await self.root.err.record_error("gpio", *self.subpath, comment="Missing value in msg", data={"path":self.subpath,"msg":msg})
                            continue

                        if val in (False,True,0,1):
                            val = bool(val)
                            try:
                                await proc(val, line, *args)
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
            line.value = val != negate
        if state is not None:
            await self.client.set(*state, value=val)

    async def _oneshot_value(self, line, val, state, negate, t_on):
        """
        Task that monitors one entry. Its value is written to the
        controller but if it's = ``direc`` it's reverted autonomously after
        ``intv`` seconds. The current state is written to ``cur``, if
        present.

        ``intv`` and ``direc`` may be numbers or paths, if the latter
        they're read from DistKV. ``cur`` must be a path.

        """

        async def work_oneshot(evt):
            nonlocal t_on
            if isinstance(t_on, (list,tuple)):
                t_on = (await self.client.get(*t_on)).value_or(None)
            async with anyio.open_cancel_scope() as sc:
                try:
                    self._work = sc
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
            await self.chip.task_group.spawn(work_oneshot, evt)
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

                        await work.wait()
            finally:
                if self._work is sc:
                    await self._work_done.set()
                    self._work = None
                    self._work_done = None

                async with anyio.fail_after(2, shield=True):
                    if state is not None:
                        try:
                            val = await self.chip.read_output(self.card, self.port)
                        except ClosedResourceError:
                            pass
                        else:
                            await self.client.set(*state, value=(val != negate))

        if val:
            evt = anyio.create_event()
            await self.chip.task_group.spawn(work_pulse, evt)
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
            # logger.debug("Port not configured: %s %s %d %d", *self.subpath[-4:])
            logger.info("mode or src not set in %s",self.subpath)
            return

        # Rest state. The input value in DistKV is always active=high.
        rest = self.find_cfg('rest', default=False)
        t_on = self.find_cfg('t_on', default=None)
        t_off = self.find_cfg('t_off', default=None)
        state = self.find_cfg('state', default=None)

        evt = anyio.create_event()
        if mode == "write":
            await self.tg.spawn(self.with_output, evt, src, self._set_value, state, rest)
        elif mode == "oneshot":
            if t_on is None:
                logger.info("t_on not set in %s",self.subpath)
                return
            await self.tg.spawn(self.with_output, evt, src, self._oneshot_value, state, rest, t_on)
        elif mode == "pulse":
            if t_on is None:
                logger.info("t_on not set in %s",self.subpath)
                return
            if t_off is None:
                logger.info("t_off not set in %s",self.subpath)
                return
            await self.tg.spawn(self.with_output, evt, src, self._pulse_value, state, rest, t_on, t_off)
        else:
            logger.info("mode not known (%r) in %s", mode, self.subpath)
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

    async def setup(self):
        await super().setup()
        s = self.chip
        if s is not None:
            await s.set_freq(self.find_cfg("poll"))
            await s.set_ping_freq(self.find_cfg("ping"))

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

