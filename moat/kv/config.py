"""
An online-updated config store

"""

from __future__ import annotations

try:
    from contextlib import asynccontextmanager
except ImportError:  # pragma: no cover
    from async_generator import asynccontextmanager

import logging

from .exceptions import ServerClosedError, ServerError
from .obj import ClientEntry, ClientRoot

logger = logging.getLogger(__name__)


class ConfigEntry(ClientEntry):  # noqa:D101
    @classmethod
    def child_type(cls, name):  # pragma: no cover  # noqa:D102
        name  # noqa:B018
        logger.warning("Online config sub-entries are ignored")
        return ClientEntry

    async def set_value(self, value):  # noqa:D102
        await self.root.client.config._update(self._name, value)  # noqa:SLF001


class ConfigRoot(ClientRoot):  # noqa:D101
    CFG = "config"

    @classmethod
    def child_type(cls, name):  # noqa:D102
        name  # noqa:B018
        return ConfigEntry

    @asynccontextmanager
    async def run(self):  # noqa:D102
        try:
            async with super().run() as x:
                yield x
        except ServerClosedError:  # pragma: no cover
            pass
        except ServerError:  # pragma: no cover
            logger.exception("No config data")
