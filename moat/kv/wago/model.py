"""
MoaT-KV client data model for Wago
"""
import anyio

from moat.util import Path
from moat.kv.obj import ClientEntry, ClientRoot
from moat.kv.errors import ErrorRoot

import logging

logger = logging.getLogger(__name__)


class _WAGObase(ClientEntry):
    """
    Forward ``_update_server`` calls to child entries.
    """

    _server = None

    @property
    def server(self):
        if self._server is None:
            self._server = self.parent.server
        return self._server

    async def set_value(self, val):  # pylint: disable=arguments-differ
        await super().set_value(val)
        if self.server is not None:
            await self._update_server()

    async def update_server(self):
        await self.parent.update_server()

    async def _update_server(self):
        if not self.val_d(True, "present"):
            return
        await self.setup()
        for k in self:
            await k._update_server()

    async def setup(self):
        pass


class _WAGOnode(_WAGObase):
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
        return self.server.task_group

    async def setup(self):
        await super().setup()
        if self.server is None:
            self._poll = None
            return

        if self._poll is not None:
            await self._poll.cancel()
            self._poll = None

        pass


class WAGOinput(_WAGOnode):
    """Describes one input port.

    An input port is polled or counted.
    """

    async def _poll_task(self, dest, *, task_status):
        with anyio.CancelScope() as sc:
            self._poll = sc
            rest = self.find_cfg("rest", default=False)
            async with self.server.monitor_input(self.card, self.port) as mon:
                task_status.started()
                async for val in mon:
                    await self.client.set(dest, value=(val != rest))

    async def _count_task(self, dest, intv, direc, *, task_status):
        with anyio.CancelScope() as sc:
            self._poll = sc
            delta = await self.client.get(dest)
            delta = delta.get("value", 0)
            if not isinstance(delta, (int, float)):
                delta = 0

            async with self.server.count_input(
                self.card, self.port, direction=direc, interval=intv
            ) as mon:
                task_status.started()
                async for val in mon:
                    await self.client.set(dest, value=val + delta)

    async def setup(self):
        await super().setup()

        if self.server is None:
            return
        try:
            mode = self.find_cfg("mode")
            dest = self.find_cfg("dest")
        except KeyError:
            logger.info("mode or dest not set in %s", self.subpath)
            # logger.debug("Port not configured: %s %s %d %d", *self.subpath[-4:])
            return

        if mode == "read":
            await self.tg.start(self._poll_task, dest)
        elif mode == "count":
            intv = self.find_cfg("interval")
            direc = self.find_cfg("count")
            await self.tg.start(self._count_task, dest, intv, direc)
        else:
            logger.info("mode not known (%r) in %s", mode, self.subpath)
            return  # mode unknown


class WAGOoutput(_WAGOnode):
    """Describes one output port.

    Output ports are written to or pulsed. In addition, a timeout may be given.
    """

    _work = None
    _work_done = None

    async def with_output(self, src, proc, *args, task_status):
        """
        Task that monitors one entry and writes its value to the Wago controller.

        Also the value is mirrored to ``cur`` if that's set.
        """
        preload = True
        with anyio.CancelScope() as sc:
            self._poll = sc
            ready = False
            async with self.client.watch(src, min_depth=0, max_depth=0, fetch=True) as wp:
                async for msg in wp:
                    try:
                        val = msg.value
                        preload = False
                    except AttributeError:
                        if msg.get("state", "") == "uptodate":
                            task_status.started()
                            ready = True
                        else:
                            await self.root.err.record_error(
                                "wago",
                                self.subpath,
                                comment="Missing value: %r" % (msg,),
                                data={"path": self.subpath}
                            )
                        continue

                    if not ready:  # TODO
                        continue

                    if val in (False, True, 0, 1):
                        val = bool(val)
                        try:
                            await proc(val, preload, *args)
                        except StopAsyncIteration:
                            await self.root.err.record_error(
                                "wago",
                                self.subpath,
                                data={"value": val},
                                comment="Stopped due to bad timer value"
                            )
                            return
                        except Exception as exc:
                            await self.root.err.record_error(
                                "wago", self.subpath, data={"value": val}, exc=exc
                            )
                        else:
                            await self.root.err.record_working("wago", self.subpath)
                    else:
                        await self.root.err.record_error(
                            "wago", self.subpath, comment="Bad value: %r" % (val,)
                        )

    async def _set_value(self, val, preload, state, negate):
        """
        Task that monitors one entry and writes its value to the Wago controller.

        Also the value is mirrored to ``cur`` if that's set.
        """
        await self.server.write_output(self.card, self.port, val != negate)
        if state is not None:
            await self.client.set(state, value=val)

    async def _oneshot_value(self, val, preload, state, negate, t_on):  # pylint: disable=unused-argument
        """
        Task that monitors one entry. Its value is written to the
        controller but if it's = ``direc`` it's reverted autonomously after
        ``intv`` seconds. The current state is written to ``cur``, if
        present.

        ``intv`` and ``direc`` may be numbers or paths, if the latter
        they're read from MoaT-KV. ``cur`` must be a path.

        """

        async def work_oneshot(task_status):
            nonlocal t_on
            if isinstance(t_on, (Path, list, tuple)):
                t_on = (await self.client.get(t_on)).value_or(None)
            try:
                with anyio.CancelScope() as sc:
                    async with self.server.write_timed_output(
                        self.card, self.port, not negate, t_on
                    ) as work:
                        self._work = sc
                        self._work_done = anyio.Event()
                        task_status.started()
                        if state is not None:
                            await self.client.set(state, value=True)

                        await work.wait()
            finally:
                with anyio.fail_after(2, shield=True):
                    if state is not None:
                        try:
                            val = await self.server.read_output(self.card, self.port)
                        except anyio.ClosedResourceError:
                            pass
                        else:
                            await self.client.set(state, value=(val != negate))
                    if self._work is sc:
                        self._work = None
                        self._work_done.set()

        if val and not preload:
            await self.server.task_group.start(work_oneshot)
        else:
            if self._work:
                await self._work.cancel()
                await self._work_done.wait()
            else:
                await self._set_value(False, None, state, negate)

    async def _pulse_value(self, val, preload, state, negate, t_on, t_off):
        """
        Pulse the value.

        The state records the cycle ratio.
        """

        async def work_pulse(task_status):
            nonlocal t_on
            nonlocal t_off
            if isinstance(t_on, (Path, list, tuple)):
                t_on = (await self.client.get(t_on)).value_or(None)
            if isinstance(t_off, (Path, list, tuple)):
                t_off = (await self.client.get(t_off)).value_or(None)
            if t_on is None or t_off is None:
                raise StopAsyncIteration

            try:
                with anyio.CancelScope() as sc:
                    async with self.server.write_pulsed_output(
                        self.card, self.port, not negate, t_on, t_off
                    ) as work:
                        self._work = sc
                        self._work_done = anyio.Event()
                        task_status.started()

                        if state is not None:
                            await self.client.set(state, value=t_on / (t_on + t_off))

                        await work.wait()
            finally:
                if self._work is sc:
                    self._work_done.set()
                    self._work = None
                    self._work_done = None

                with anyio.fail_after(2, shield=True):
                    if state is not None:
                        try:
                            val = await self.server.read_output(self.card, self.port)
                        except anyio.ClosedResourceError:
                            pass
                        else:
                            await self.client.set(state, value=(val != negate))

        if val:
            await self.server.task_group.start(work_pulse)
        else:
            if self._work:
                await self._work.cancel()
                await self._work_done.wait()
            else:
                await self._set_value(False, None, state, negate)

    async def setup(self):
        await super().setup()
        if self.server is None:
            return
        if self._work:
            await self._work.aclose()

        try:
            mode = self.find_cfg("mode")
            src = self.find_cfg("src")
        except KeyError:
            # logger.debug("Port not configured: %s %s %d %d", *self.subpath[-4:])
            logger.info("mode or src not set in %s", self.subpath)
            return

        # Rest state. The input value in MoaT-KV is always active=high.
        rest = self.find_cfg("rest", default=False)
        t_on = self.find_cfg("t_on", default=None)
        t_off = self.find_cfg("t_off", default=None)
        state = self.find_cfg("state", default=None)

        if mode == "write":
            await self.tg.start(self.with_output, src, self._set_value, state, rest)
        elif mode == "oneshot":
            if t_on is None:
                logger.info("t_on not set in %s", self.subpath)
                return
            await self.tg.start(self.with_output, src, self._oneshot_value, state, rest, t_on)
        elif mode == "pulse":
            if t_on is None:
                logger.info("t_on not set in %s", self.subpath)
                return
            if t_off is None:
                logger.info("t_off not set in %s", self.subpath)
                return
            await self.tg.start(
                self.with_output, src, self._pulse_value, state, rest, t_on, t_off
            )
        else:
            logger.info("mode not known (%r) in %s", mode, self.subpath)
            return


class _WAGObaseNUM(_WAGObase):
    """
    A path element between 1 and 99 inclusive works.
    """

    cls = None

    @classmethod
    def child_type(cls, name):
        if isinstance(name, int) and name > 0 and name < 100:
            return cls.cls
        return None


class WAGOinputCARD(_WAGObaseNUM):
    cls = WAGOinput


class WAGOoutputCARD(_WAGObaseNUM):
    cls = WAGOoutput


class WAGOinputBase(_WAGObaseNUM):
    cls = WAGOinputCARD


class WAGOoutputBase(_WAGObaseNUM):
    cls = WAGOoutputCARD


class _WAGObaseSERV(_WAGObase):
    async def set_value(self, val):
        await super().set_value(val)
        await self.update_server()


class WAGOserver(_WAGObaseSERV):
    _server = None

    @classmethod
    def child_type(cls, name):
        if name == "input":
            return WAGOinputBase
        if name == "output":
            return WAGOoutputBase
        return None

    @property
    def server(self):
        return self._server

    async def set_server(self, server):
        self._server = server
        await self._update_server()

    async def setup(self):
        await super().setup()
        s = self.server
        if s is not None:
            await s.set_freq(self.find_cfg("poll"))
            await s.set_ping_freq(self.find_cfg("ping"))


class WAGOroot(_WAGObase, ClientRoot):
    cls = {}
    reg = {}
    CFG = "wago"
    err = None

    async def run_starting(self, server=None):  # pylint: disable=arguments-differ
        self._server = server
        if self.err is None:
            self.err = await ErrorRoot.as_handler(self.client)
        await super().run_starting()

    @classmethod
    def register(cls, typ):
        def acc(kls):
            cls.reg[typ] = kls
            return kls

        return acc

    def child_type(self, name):
        return WAGOserver

    async def update_server(self):
        await self._update_server()
