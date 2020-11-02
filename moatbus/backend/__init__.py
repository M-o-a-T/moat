#
"""
Base class for sending MoaT messages on a Trio system
"""

from contextlib import asynccontextmanager

from ..message import BusMessage
from ..util import CtxObj

class BaseBusHandler(CtxObj):
    """
    This class defines the interface for exchanging MoaT messages.

    Usage::
        
        async with SomeBusHandler(some, params).ctx as bus:
            await bus.send(some_msg)
            async for msg in bus:
                await process(msg)
    """

    def __init__(self, name=None):
        self.name = name

    @asynccontextmanager
    async def _ctx(self):
        yield self

    async def send(self, msg:BusMessage):
        raise RuntimeError("Override @send!")

    def __aiter__(self):
        raise RuntimeError("Override @__aiter__!")

    async def __anext__(self):
        raise RuntimeError("Override @__anext__!")
