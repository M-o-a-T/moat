"""
MoaT-KV client data model for KNX
"""
import anyio

from moat.util import NotGiven
from moat.kv.obj import ClientEntry, ClientRoot
from moat.kv.errors import ErrorRoot

from xknx.telegram import GroupAddress
from xknx.devices import Sensor, BinarySensor, Switch, ExposeSensor
from xknx.remote_value import RemoteValueSensor


import logging

logger = logging.getLogger(__name__)


class _KNXbase(ClientEntry):
    """
    Forward ``_update_server`` calls to child entries.
    """

    _server = None

    @property
    def server(self):
        if self._server is None:
            self._server = self.parent.server
        return self._server

    async def set_value(self, value):
        await super().set_value(value)
        if self.server is not None:
            await self._update_server()

    async def update_server(self):
        await self.parent.update_server()

    async def _update_server(self, initial=False):
        if not self.val_d(True, "present"):
            return
        await self.setup(initial=initial)
        for k in self:
            await k._update_server(initial=initial)

    async def setup(self, initial=False):
        pass


class _KNXnode(_KNXbase):
    """
    Base class for a single input or output.
    """

    _task = None
    _task_done = None

    @property
    def group(self):
        assert 0 <= self._path[-3] < 1 << 5
        assert 0 <= self._path[-2] < 1 << 3
        assert 0 <= self._path[-1] < 1 << 8
        return GroupAddress((self._path[-3] << 11) | (self._path[-2] << 8) | self._path[-1])

    @property
    def tg(self):
        return self.server.task_group

    async def setup(self, initial=False):
        await super().setup()
        if self.server is None:
            self._task = None
            return
        await self._kill()

    async def _kill(self):
        if self._task is not None:
            await self._task.cancel()
            await self._task_done.wait()
            self._task = None

    async def spawn(self, p, *a, **k):
        async def _spawn(p, a, k, task_status=anyio.TASK_STATUS_IGNORED):
            await self._kill()
            with anyio.CancelScope() as sc:
                self._task = sc
                self._task_done = anyio.Event()
                task_status.started()
                try:
                    await p(*a, **k)
                finally:
                    with anyio.CancelScope(shield=True):
                        self._task_done.set()

        await self.tg.start(_spawn, p, a, k)


class KNXnode(_KNXnode):
    """Describes one port, i.e. incoming value to be read."""

    async def _task_in(self, evt, dest):
        try:
            idem = self.find_cfg("idem", default=True)

            mode = self.find_cfg("mode", default=None)
            if mode is None:
                logger.info("mode not set in %s", self.subpath)
                return

            args = dict(
                xknx=self.server,
                group_address_state=self.group,
                name=mode + "." + ".".join(str(x) for x in self.subpath),
                ignore_internal_state=True,
            )
            if mode == "binary":
                device = BinarySensor(**args)
                get_val = lambda s: s.is_on()

            elif mode in RemoteValueSensor.DPTMAP:
                device = Sensor(value_type=mode, **args)
                get_val = lambda s: s.sensor_value.value
            # TODO more of the same
            else:
                logger.info("mode not known (%r) in %s", mode, self.subpath)
                return

            async with device.run() as dev:
                evt.set()
                async for _ in dev:
                    await self.client.set(dest, value=get_val(device), idem=idem)
        finally:
            evt.set()

    async def _task_out(self, evt, src, initial=False):
        try:
            val = None
            idem = self.find_cfg("idem", default=True)
            mode = self.find_cfg("mode", default=None)
            if mode is None:
                logger.info("mode not set in %s", self.subpath)
                return

            args = dict(
                xknx=self.server,
                group_address=self.group,
                name=mode + "." + ".".join(str(x) for x in self.subpath),
            )
            if mode == "binary":
                device = Switch(**args)

                async def set_val(dev, val):
                    if val:
                        await dev.set_on()
                    else:
                        await dev.set_off()

                def get_val(dev):
                    return dev.state

            elif mode in RemoteValueSensor.DPTMAP:
                device = ExposeSensor(value_type=mode, **args)

                async def set_val(dev, val):
                    return await dev.set(val)

                def get_val(device):
                    return device.sensor_value.value

            else:
                logger.info("mode not known (%r) in %s", mode, self.subpath)
                return

            async with anyio.create_task_group() as tg:
                lock = anyio.Lock()
                chain = None

                async def _rdr(task_status=anyio.TASK_STATUS_IGNORED):
                    # The "goal" value may also be set by the bus. Thus we monitor
                    # the device we send on, and set the value accordingly.
                    nonlocal val
                    async with device.run() as dev:
                        task_status.started()
                        async for _ in dev:
                            nval = get_val(device)
                            if val is None or nval != val:
                                async with lock:
                                    val = nval
                                    res = await self.client.set(
                                        src, value=val, nchain=1, idem=idem
                                    )
                                    nonlocal chain
                                    chain = res.chain

                await tg.start(_rdr)

                async with self.client.watch(
                    src, min_depth=0, max_depth=0, fetch=initial, nchain=1
                ) as wp:
                    evt.set()
                    async for msg in wp:
                        if "path" not in msg:
                            continue
                        if msg.get("value", NotGiven) is NotGiven:
                            continue
                        async with lock:
                            if msg.chain == chain:
                                # This command is the one we previously
                                # received, so don#t send it back out.
                                continue
                            val = msg.value
                            await set_val(device, val)

        finally:
            evt.set()

    async def setup(self, initial=False):
        await super().setup(initial=initial)

        if self.server is None:
            return

        evt = anyio.Event()
        typ = self.find_cfg("type")
        if typ == "in":
            dest = self.find_cfg("dest", default=None)
            if dest is not None:
                await self.spawn(self._task_in, evt, dest)
            else:
                logger.info("'dest' not set in %s", self.subpath)
                return
        elif typ == "out":
            src = self.find_cfg("src", default=None)
            if src is not None:
                await self.spawn(self._task_out, evt, src, initial)
            else:
                logger.info("'src' not set in %s", self.subpath)
                return
        else:
            logger.info("type not known (%r) in %s", typ, self.subpath)
            return
        await evt.wait()


class _KNXbaseNUM(_KNXbase):
    """
    A path element between 1 and 99 inclusive works.
    """

    cls = None
    max_nr = None

    @classmethod
    def child_type(cls, name):
        if isinstance(name, int) and name >= 0 and name <= cls.max_nr:
            return cls.cls
        return None


class KNXg2(_KNXbaseNUM):
    cls = KNXnode
    max_nr = 255


class KNXg1(_KNXbaseNUM):
    cls = KNXg2
    max_nr = 7


class KNXserver(_KNXbase):
    async def set_server(self, server, initial=False):
        await self.parent.set_server(server, initial=initial)


class KNXbus(_KNXbaseNUM):
    cls = KNXg1
    max_nr = 31

    _server = None

    @classmethod
    def child_type(cls, name):
        if isinstance(name, str):
            return KNXserver
        return super().child_type(name)

    async def set_value(self, value):
        await super().set_value(value)
        await self.update_server()

    @property
    def server(self):
        return self._server

    async def set_server(self, server, initial=False):
        self._server = server
        await self._update_server(initial=initial)


class KNXroot(_KNXbase, ClientRoot):
    cls = {}
    reg = {}
    CFG = "knx"
    err = None

    @property
    def server(self):
        return None

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
        return KNXbus

    async def update_server(self):
        await self._update_server()
