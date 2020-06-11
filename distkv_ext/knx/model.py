"""
DistKV client data model for KNX
"""
import anyio
from anyio.exceptions import ClosedResourceError

from distkv.obj import ClientEntry, ClientRoot
from distkv.util import combine_dict
from distkv.errors import ErrorRoot
from collections import Mapping

from xknx.telegram import GroupAddress
from xknx.devices import Sensor
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

    async def set_value(self, val):
        await super().set_value(val)
        if self.server is not None:
            await self._update_server()

    async def update_server(self):
        await self.parent.update_server()

    async def _update_server(self):
        if not self.val_d(True,'present'):
            return
        await self.setup()
        for k in self:
            await k._update_server()

    async def setup(self):
        pass

class _KNXnode(_KNXbase):
    """
    Base class for a single input or output.
    """
    _poll = None

    @property
    def group(self):
        assert 0 <= self._path[-3] < 1<<5
        assert 0 <= self._path[-2] < 1<<3
        assert 0 <= self._path[-1] < 1<<8
        return GroupAddress((self._path[-3]<<11) | (self._path[-2] << 8) | self._path[-1])

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


class KNXnode(_KNXnode):
    """Describes one port, i.e. incoming value to be read.
    """
    _task_scope = None

    async def _task_in(self, evt, dest):
        try:
            mode = self.find_cfg('mode', default=None)
            if mode is None:
                logger.info("mode not set in %s", self.subpath)
                return

            args = dict(xknx=self.server, group_address_state=self.group,
                        name=mode+"."+".".join(str(x) for x in self.subpath))
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

            async with anyio.open_cancel_scope() as sc:
                self._task_scope = sc
                async with device.run() as dev:
                    await evt.set()
                    async for _ in dev:
                        await self.client.set(*dest, value=get_val(device))
        finally:
            self._task_scope = None
            await evt.set()


    async def _task_out(self, evt, src):
        try:
            mode = self.find_cfg('mode', None)
            if mode is None:
                logger.info("mode not set in %s", self.subpath)
                return

            args = dict(xknx=self.server, group_address=self.group,
                        name=mode+"."+".".join(str(x) for x in self.subpath))
            if mode == "switch":
                device = Switch(**args)
                async def set_val(dev, val):
                    if val:
                        await dev.set_on()
                    else:
                        await dev.set_off()
            elif mode in RemoteValueSensor.DPTMAP:
                device = ExposeSensor(value_type=mode, **args)
                set_val = device.set
            else:
                logger.info("mode not known (%r) in %s", mode, self.subpath)
                return

            async with anyio.open_cancel_scope() as sc:
                self._task_scope = sc
                try:
                    async with self.client.watch(*src, min_depth=0, max_depth=0, fetch=True) as wp:
                        await evt.set()
                        async for msg in wp:
                            if msg.value is NotGiven:
                                continue
                            await set_val(device, msg.value)
                finally:
                    if self._task_scope == sc:
                        self._task_scope = None

        finally:
            await evt.set()

    async def setup(self):
        await super().setup()

        if self.server is None:
            return

        typ = self.find_cfg('type')

        if self._task_scope is not None:
            await self._task_scope.cancel()

        evt = anyio.create_event()
        if typ == "in":
            dest = self.find_cfg('dest', default=None)
            if dest is not None:
                await self.tg.spawn(self._task_in, evt, dest)
            else:
                logger.info("destination not set in %s", self.subpath)
                return
        elif typ == "out":
            src = self.find_cfg('src', default=None)
            if src is not None:
                await self.tg.spawn(self._task_out, evt, src)
            else:
                logger.info("source not set in %s", self.subpath)
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
        if isinstance(name,int) and name >= 0 and name <= cls.max_nr:
            return cls.cls
        return None

class KNXg2(_KNXbaseNUM):
    cls = KNXnode
    max_nr = 255

class KNXg1(_KNXbaseNUM):
    cls = KNXg2
    max_nr = 7

class KNXserver(_KNXbase):
    async def set_server(self, server):
        await self.parent.set_server(server)

class KNXbus(_KNXbaseNUM):
    cls = KNXg1
    max_nr = 31

    _server = None

    @classmethod
    def child_type(cls, name):
        if isinstance(name, str):
            return KNXserver
        return super().child_type(name)

    async def set_value(self, val):
        await super().set_value(val)
        await self.update_server()

    @property
    def server(self):
        return self._server

    async def set_server(self, server):
        self._server = server
        await self._update_server()


class KNXroot(_KNXbase, ClientRoot):
    cls = {}
    reg = {}
    CFG = "knx"
    err = None

    async def run_starting(self, server=None):
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

