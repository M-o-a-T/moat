from distkv.obj import ClientEntry, ClientRoot
from distkv.util import combine_dict
from distkv.errors import ErrorRoot
from collections import Mapping

class OWFSnode(ClientEntry):
    poll = None
    dev = None

    @classmethod
    def child_type(cls, name):
        return ClientEntry

    @property
    def family(self):
        return self._path[-2]

    async def with_device(self, dev):
        self.dev = dev
        await self._update_value()

    async def set_value(self, val):
        await super().set_value(val)
        await self._update_value()

    async def _update_value(self):
        if self.dev is None or self.dev.bus is None:
            return

        val = combine_dict(self.value_or({}, Mapping), self.parent.value_or({}, Mapping))

        p = val.get('poll',{})
        dev = self.dev
        if dev is not None:
            if self.poll is not None:
                for k,v in self.poll.items():
                    if k not in p:
                        await dev.set_polling_interval(k,None)
                        await self.root.err.record_working(("owfs","poll"), *self.subpath, k, comment="deleted", data={"interval":v})
            for k,v in p.items():
                if self.poll is None or self.poll.get(k,-1) != v:
                    try:
                        await dev.set_polling_interval(k,v)
                    except Exception as exc:
                        await self.root.err.record_error(("owfs","poll"), *self.subpath, k, data={"interval":v}, exc=exc)
                    else:
                        await self.root.err.record_working(("owfs","poll"), *self.subpath, k, comment="replaced", data={"interval":v})

        self.poll = p


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


class OWFSroot(ClientRoot):
    cls = {}
    reg = {}
    CFG = "owfs"
    err = None

    async def run_starting(self):
        if self.err is None:
            self.err = await ErrorRoot.as_handler(self.client)
        await super().run_starting()

    @classmethod
    def register(cls, typ):
        def acc(kls):
            cls.reg[typ] = kls
            return kls
        return acc

    @classmethod
    def child_type(kls, name):
        if not isinstance(name,int):
            return ClientEntry
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


