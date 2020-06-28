"""
DistKV client data model for Akumuli
"""
import anyio
from anyio.exceptions import ClosedResourceError

from distkv.obj import ClientEntry, ClientRoot
from distkv.util import combine_dict
from distkv.errors import ErrorRoot
from collections import Mapping

import logging
logger = logging.getLogger(__name__)
        
class _AkumuliBase(ClientEntry):
    """
    Forward ``_update_server`` calls to child entries.
    """
    _server = None

    @property
    def server(self):
        return self.parent.server

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

class AkumuliNode(_AkumuliBase):
    """
    Base class for a node with data (possibly).
    """
    _work = None

    @property
    def tg(self):
        return self.parent.tg

    async def setup(self):
        await super().setup()
        if self.server is None:
            self._poll = None
            return

        if self._poll is not None:
            await self._poll.cancel()
            self._poll = None

        pass

    async def with_output(self, evt, src)
        """
        Task that monitors one entry and writes its value to Akumuli.
        """
        async with anyio.open_cancel_scope() as sc:
            self._work = sc
            async with self.client.watch(*src, min_depth=0, max_depth=0, fetch=True) as wp:
                await evt.set()
                async for msg in wp:
                    try:
                        val = msg.value
                    except AttributeError:
                        if msg.get("state","") != "uptodate":
                            await self.root.err.record_error("akumuli", *self.subpath, comment="Missing value: %r" % (msg,), data={"path":self.subpath})
                        continue

                    await proc(val, *args)  # XXX

    async def setup(self):
        await super().setup()
        if self.server is None:
            return

        if self._work is not None:
            await self._work.cancel()
        await self.tg.spawn(self.with_output, evt, src)
        await evt.wait()


class AkumuliServer(_AkumuliBase):
    _server = None

    @classmethod
    def child_type(cls, name):
        return AkumuliNode

    @property
    def server(self):
        return self._server

    async def set_server(self, server):
        self._server = server
        await self._update_server()


class AkumuliRoot(_AkumuliBase, ClientRoot):
    CFG = "akumuli"
    err = None

    async def run_starting(self, server=None):
        self._server = server
        if self.err is None:
            self.err = await ErrorRoot.as_handler(self.client)
        await super().run_starting()

    def child_type(self, name):
        return AkumuliServer

    async def update_server(self):
        await self._update_server()

