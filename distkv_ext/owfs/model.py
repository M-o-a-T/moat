"""
DistKV client data model for 1wire
"""
import anyio

from distkv.obj import ClientEntry, ClientRoot, AttrClientEntry
from distkv.util import combine_dict
from distkv.errors import ErrorRoot
from collections.abc import Mapping

import logging
logger = logging.getLogger(__name__)
        
class OWFSnode(ClientEntry):
    poll = None
    dev = None

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.poll = {}
        self.monitors = {}

    @property
    def node(self):
        return self

    @property
    def family(self):
        return self._path[-2]

    async def sync(self):
        for k in self:
            await k.sync()

    async def with_device(self, dev):
        """
        Called by the OWFS monitor, noting that the device is now visible
        on a bus (or not, if ``None``).
        """
        self.dev = dev
        await self._update_value()

    async def set_value(self, val):
        """
        Some attribute has been updated.
        """
        await super().set_value(val)
        await self._update_value()

    async def _update_value(self):
        """
        Synpollers, watchers and attributes.
        """
        dev = self.dev
        if dev is None or dev.bus is None:
            return

        v = self.value_or({}, Mapping)
        val = combine_dict(v, self.parent.value_or({}, Mapping))

        dev = self.dev
        if dev is None or dev.bus is None:
            self.poll = {}  # the bus forgets them
            # self.monitors is cleared by the tasks
        else:
            obus = v.get('bus',{})
            bus = dict(server=dev.bus.server.name, path=dev.bus.path)
            if bus != obus:
                v['bus'] = bus
                await self.update(v)
            
            poll = val.get('attr',{})

            # set up polling
            for k,v in self.poll.items():
                kp = poll.get(k,{})
                if not kp.get('dest',()) or kp.get('interval',-1) <= 0:
                    logger.error("POLL OFF 1 %s",k)
                    await dev.set_polling_interval(k,0)
                    await self.root.err.record_working("owfs", *self.subpath, k, "poll", comment="deleted")

            for k,v in list(self.monitors.items()):
                kp = poll.get(k,{})
                if kp.get('src',()) != self.poll.get(k,{}).get('src',()):
                    logger.error("POLL OFF 2 %s",k)
                    await dev.set_polling_interval(k,0)
                    await v.cancel()
                    await self.root.err.record_working("owfs", *self.subpath, k, "write", comment="deleted")

            for k,v in poll.items():
                kp = self.poll.get(k,{})
                try:
                    if v.get('dest',()):
                        i = v.get('interval',-1)
                        if i > 0:
                            if not kp.get('dest',()) or kp.get('interval',-1) != i:
                                logger.error("POLL ON %s %s",k,v)
                                await dev.set_polling_interval(k,v['interval'])
                            await self.root.err.record_working("owfs", *self.subpath, k, "poll", comment="replaced", data=v)
                except Exception as exc:
                    await self.root.err.record_error("owfs", *self.subpath, k, "poll", data=v, exc=exc)

                vp = v.get('src',())
                if vp:
                    if kp.get('src',()) != vp or k not in self.monitors:
                        evt = anyio.create_event()
                        await self.client.tg.spawn(self._watch, k, v['src'], evt)
                        await evt.wait()


            self.poll = poll

    async def _watch(self, k, src, evt):
        """
        Task that monitors one entry and writes its value to the 1wire
        device.

        TODO select an attribute.
        """
        async with anyio.open_cancel_scope() as sc:
            try:
                async with self.client.watch(*src, min_depth=0, max_depth=0, fetch=True) as wp:
                    if self.monitors.get(k, None) is not None:
                        await self.monitors[k].cancel()
                    self.monitors[k] = sc

                    await evt.set()
                    kp = [x for x in k.split('/') if k]
                    await self.root.err.record_working("owfs", *self.subpath, k, "write", comment="replaced")

                    async for msg in wp:
                        try:
                            val = msg.value
                        except AttributeError:
                            pass
                        else:
                            if self.dev is None:
                                await self.root.err.record_error("owfs", *self.subpath, k, "write", comment="device missing")
                                return
                            await self.dev.attr_set(*kp, value=val)
            except Exception as exc:
                await self.root.err.record_error("owfs", *self.subpath, k, "write", exc=exc)
            finally:
                if self.monitors.get(k, None) is sc:
                    del self.monitors[k]


class OWFSfamily(ClientEntry):
    cls = OWFSnode

    @classmethod
    def child_type(cls, name):
        if not isinstance(name,int):
            return ClientEntry
        if name<=0 or name>16**12:
            return ClientEntry
        return cls.cls

    async def set_value(self, val):
        await super().set_value(val)
        for c in self:
            await c._update_value()


class ServerEntry(AttrClientEntry):
    ATTRS = ("server",)

    @classmethod
    def child_type(cls, name):
        return ClientEntry


class ServerRoot(ClientEntry):
    @classmethod
    def child_type(cls, name):
        return ServerEntry


class OWFSroot(ClientRoot):
    cls = {}
    reg = {}
    CFG = "owfs"
    err = None

    async def run_starting(self):
        if self.err is None:
            self.err = await ErrorRoot.as_handler(self.client)
        await super().run_starting()

    @property
    def server(self):
        return self['server']

    @classmethod
    def register(cls, typ):
        def acc(kls):
            cls.reg[typ] = kls
            return kls
        return acc

    @classmethod
    def child_type(kls, name):
        if not isinstance(name,int):
            return ServerRoot
        if name<0 or name>255:
            return ClientEntry
        try:
            return kls.cls[name]
        except KeyError:
            class FamilyX(OWFSfamily):
                cls = kls.reg.get(name, OWFSnode)
            FamilyX.__name__ = "OWFSfamily_%02X" % (name,)
            kls.cls[name] = FamilyX
            return FamilyX

@OWFSroot.register(0x10)
class TempNode(OWFSnode):
    CFG = {"temperature": 30}


