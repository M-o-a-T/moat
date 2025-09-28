"""
dbus helpers
"""

from __future__ import annotations

import anyio
from contextlib import asynccontextmanager

from asyncdbus.constants import NameFlag
from asyncdbus.service import dbus as dbus_

from moat.util import CtxObj

INTF = "org.m_o_a_t"
NAME = "org.m_o_a_t"


def reg_name(base, name):
    "Build registration name"
    if name is None:
        name = NAME
    elif name[0] == "+":
        name = f"{base}.{name[1:]}"
    elif "." not in name:
        name = f"{base}.{name}"
    return name


@asynccontextmanager
async def DbusName(dbus, name=None):
    """
    Context manager to register a name on DBus
    """
    await dbus.request_name(reg_name(NAME, name), NameFlag.DO_NOT_QUEUE)
    try:
        yield None
    finally:
        with anyio.move_on_after(2, shield=True):
            await dbus.release_name(name)


class DbusInterface(dbus_.ServiceInterface, CtxObj):
    """
    Wrapper to export an interface
    """

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
