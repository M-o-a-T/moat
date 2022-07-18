"""
DistKV client data model for MoaT bus devices
"""
import anyio

import asyncclick as click

from distkv.obj import ClientEntry, ClientRoot, AttrClientEntry
from distkv.util import NotGiven, Path
from distkv.errors import ErrorRoot

class _MOATbase(ClientEntry):
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


class MOATnode(_MOATbase):
    """
    Base class for a bus device.
    """

    _task = None
    _task_done = None

    @property
    def tg(self):
        return self.server.task_group

    async def with_device(self, dev):
        """
        Called by the OWFS monitor, noting that the device is now visible
        on a bus (or not, if ``None``).
        """
        self.dev = dev
        await self._update_value()
        await self.sync(True)

    async def set_value(self, val):  # pylint: disable=arguments-differ
        """
        Some attribute has been updated.
        """
        await super().set_value(val)
        await self._update_value()
        await self.sync(False)

    async def _update_value(self):
        """
        Synpollers, watchers and attributes.
        """
        dev = self.dev
        if dev is None or dev.bus is None:
            return

        self.val = combine_dict(self.value_or({}, Mapping), self.parent.value_or({}, Mapping))

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
        evt = anyio.create_event()

        async def _spawn(evt, p, a, k):
            await self._kill()
            async with anyio.open_cancel_scope() as sc:
                self._task = sc
                self._task_done = anyio.create_event()
                await evt.set()
                try:
                    await p(*a, **k)
                finally:
                    async with anyio.open_cancel_scope(shield=True):
                        await self._task_done.set()

        await self.tg.spawn(_spawn, evt, p, a, k)
        await evt.wait()

def conn_backend(name):
    from importlib import import_module

    if "." not in name:
        name = "moatbus.backend." + name
    return import_module(name).Handler


class MOATconn(_MOATbase, AttrClientEntry):
    """Describes one possible connection to this bus."""
    typ = None
    params = None
    host = None

    ATTRS = ("typ","params","host")

    def __init__(self,*a,**k):
        self.params = {}
        super().__init__(*a,**k)

    def __str__(self):
        if self.typ is None:
            return "Conn:??"
        res = f"{self._name}: {self.typ} {self.handler.repr(self.params)}"
        if self.host is not None:
            res += f" @{self.host}"
        return res

    async def set_value(self, value):
        await super().set_value(value)
        if self.typ is None:
            self.params = {}

    async def save(self):
        self.check_config(self.typ, self.host, self.params)
        await super().save()

    @property
    def handler(self):
        """
        The handler for this type.
        """
        return conn_backend(self.typ)

    def backend(self):
        """
        The backend's context manager. Usage::

            async with this.backend as r:
                await r.send(hello_msg)
                async for msg in r:
                    await process(msg)
        """
        if self.host is not None and self.root.client.client_name != self.host:
            raise RuntimeError(f"This must run on {self.host}. This is {self.root.client.client_name}")
        return self.handler(self.root.client, **self.params)

    @staticmethod
    def check_config(typ, host, params):
        """
        Check whether these parameters are OK
        """
        # XXX this is something of an abuse of `click.MissingParameter`.
        if typ is None:
            raise click.MissingParameter(param_hint="", param_type="type")
        back = conn_backend(typ)
        if back.need_host and host is None:
            raise click.MissingParameter(param_hint="", param_type="host", message="Required by this type.")
        back.check_config(params)

class MOATbus(_MOATbase, AttrClientEntry):
    """Describes one bus, i.e. a collection of clients"""
    ATTRS = ('topic',)
    topic: str = None

    @classmethod
    def child_type(cls, name):
        if isinstance(name, str):
            return MOATconn
        return super().child_type(name)

    async def set_value(self, value):
        await super().set_value(value)
        await self.update_server()

    def __str__(self):
        return f"{self._name}: {self.topic}"

    @property
    def server(self):
        return self._server

    async def set_server(self, server, initial=False):
        self._server = server
        await self._update_server(initial=initial)

    async def save(self):
        if self.topic is None:
            raise click.MissingParameter(param_hint="", param_type="topic", message="You need to specify a topic path.")
        await super().save()

    @property
    def repr(self):
        res = attrdict()
        res.name = self.name
        res.topic = self.topic
        return res



class MOATbuses(_MOATbase):
    @classmethod
    def child_type(cls, name):
        if isinstance(name, str):
            return MOATbus
        return ClientEntry


class MOATroot(_MOATbase, ClientRoot):
    reg = {}
    CFG = "moatbus"
    err = None

    @property
    def server(self):
        return None

    @property
    def bus(self):
        return self.follow(Path("bus"))

    async def run_starting(self, server=None):  # pylint: disable=arguments-differ
        self._server = server
        if self.err is None:
            self.err = await ErrorRoot.as_handler(self.client)
        await super().run_starting()

    def child_type(self, name):
        if name == "type":
            return MOATtype
        if name == "bus":
            return MOATbuses
        if name == "device":
            return MOATdevs
        return super().child_type(name)

    async def update_server(self):
        await self._update_server()
