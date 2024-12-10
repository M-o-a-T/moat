#
# dbus helpers

from contextlib import asynccontextmanager
import asyncdbus.service as dbus
from asyncdbus.constants import NameFlag
from moat.util import CtxObj
import anyio

INTF = "org.m_o_a_t"
NAME = "org.m_o_a_t"

def reg_name(base, name):
    if name is None:
        name = NAME
    elif name[0] == "+":
        name = f"{base}.{name[1:]}"
    elif '.' not in name:
        name = f"{base}.{name}"
    return name

@asynccontextmanager
async def DbusName(dbus, name=None):
    await dbus.request_name(reg_name(NAME, name), NameFlag.DO_NOT_QUEUE)
    try:
        yield None
    finally:
        with anyio.move_on_after(2, shield=True):
            await dbus.release_name(name)


class DbusInterface(dbus.ServiceInterface, CtxObj):
    def __init__(self, dbus, path, interface=None):
        self.dbus = dbus
        self.path = path
        super().__init__(reg_name(INTF, interface))

    @asynccontextmanager
    async def _ctx(self):
        await self.dbus.export(self.path, self)
        try:
            yield self
        finally:
            with anyio.move_on_after(2, shield=True):
                await self.dbus.unexport(self.path, self)

