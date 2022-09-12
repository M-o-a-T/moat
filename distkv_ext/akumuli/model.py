"""
DistKV client data model for Akumuli
"""
import anyio
from collections.abc import Mapping

from distkv.obj import ClientEntry, ClientRoot, AttrClientEntry
from distkv.errors import ErrorRoot
from distkv.util import NotGiven, attrdict, Path
from asyncakumuli import Entry, DS

import logging

logger = logging.getLogger(__name__)


def _test_hook(e: Entry):  # pylint: disable=unused-argument
    pass


class _AkumuliBase(ClientEntry):
    """
    Forward ``_update_server`` calls to child entries.
    """

    _server = None

    @property
    def server(self):
        return self.parent.server

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


class AkumuliNode(_AkumuliBase, AttrClientEntry):
    """
    Base class for a node with data (possibly).
    """
    attr = None
    mode = None
    source = None
    series = None
    tags = None
    t_min = None
    ATTRS = ('source', 'attr', 'mode', 'series', 'tags', 't_min')

    _work = None
    _t_last = None

    @property
    def tg(self):
        return self.parent.tg

    def __str__(self):
        return f"N {Path(*self.subpath[1:])} {Path(*self.source)} {Path(*self.attr)} {self.series} {' '.join('%s=%s' % (k,v) for k,v in self.tags.items())}"

    async def with_output(self, evt, src, attr, series, tags, mode):
        """
        Task that monitors one entry and writes its value to Akumuli.
        """
        async with anyio.open_cancel_scope() as sc:
            self._work = sc
            async with self.client.watch(src, min_depth=0, max_depth=0, fetch=True) as wp:
                await evt.set()
                async for msg in wp:
                    try:
                        val = msg.value
                    except AttributeError:
                        if msg.get("state", "") != "uptodate":
                            await self.root.err.record_error(
                                "akumuli",
                                self.subpath,
                                message="Missing value: {msg}",
                                data={"path": self.subpath, "msg": msg},
                            )
                        continue
                    if self.t_min is not None:
                        t = anyio.current_time()
                        if self._t_last is not None and self._t_last+self.t_min < t:
                            continue
                        self._t_last = t

                    oval = val
                    for k in attr:
                        try:
                            val = val[k]
                        except KeyError:
                            await self.root.err.record_error(
                                "akumuli",
                                self.subpath,
                                data=dict(value=oval, attr=attr, message="Missing attr"),
                            )
                            continue

                    e = Entry(series=series, mode=mode, value=val, tags=tags)
                    _test_hook(e)
                    await self.server.put(e)
                    await self.root.err.record_working("akumuli", self.subpath)

    async def setup(self):
        await super().setup()
        if self._work is not None:
            await self._work.cancel()
            self._work = None
        if self.server is None:
            return

        if self.value is NotGiven:
            await self.root.err.record_working("akumuli", self.subpath, comment="deleted")
            return
        data = self.value_or({}, Mapping)

        src = data.get("source", None)
        series = data.get("series", None)
        tags = data.get("tags", None)
        attr = data.get("attr", ())
        mode = data.get("mode", DS.gauge)

        if src is None or len(src) == 0 or series is None or not tags or mode is None:
            await self.root.err.record_error(
                "akumuli", self.subpath, data=self.value, message="incomplete data"
            )
            return

        if isinstance(mode, str):
            mode = getattr(DS, mode, None)

        evt = anyio.create_event()
        await self.tg.spawn(self.with_output, evt, src, attr, series, tags, mode)
        await evt.wait()


class AkumuliServer(_AkumuliBase, AttrClientEntry):
    _server = None
    host:str = None
    port:int = None

    topic:str = None

    ATTRS=("topic",)
    AUX_ATTRS=("host","port")

    def __str__(self):
        res = f"{self._name}: {self.host}:{self.port}"
        if self.topic:
            res += " Topic:"+str(self.topic)
        return res

    @classmethod
    def child_type(cls, name):
        return AkumuliNode

    @property
    def server(self):
        return self._server

    @property
    def tg(self):
        return self._server._distkv__tg

    async def set_value(self, val):
        if val is NotGiven:
            return
        self.host = val.get("server",{}).get("host",None)
        self.port = val.get("server",{}).get("port",None)
        self.topic = val.get("topic",None)

    def get_value(self, **kw):
        res = super().get_value(**kw)
        try:
            s = res["server"]
        except KeyError:
            res["server"] = s = {}
        s['host'] = self.host
        s['port'] = self.port
        return res

    async def set_server(self, server):
        self._server = server
        await self._update_server()

    async def flush(self):
        await self.server.flush()


class AkumuliRoot(_AkumuliBase, ClientRoot):
    CFG = "akumuli"
    err = None

    async def run_starting(self, server=None):  # pylint: disable=arguments-differ
        self._server = server
        if self.err is None:
            self.err = await ErrorRoot.as_handler(self.client)
        await super().run_starting()

    def child_type(self, name):
        return AkumuliServer

    async def update_server(self):
        await self._update_server()
