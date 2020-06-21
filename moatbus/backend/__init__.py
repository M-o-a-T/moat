#
"""
Base class for sending MoaT messages on a Trio system
"""

from contextlib import asynccontextmanager

from ..message import BusMessage

class BaseBusHandler:
    """
    This class defines the interface for exchanging MoaT messages.

    Usage::
        
        async with SomeBusHandler(some, params).ctx as bus:
            async for msg in bus:
                await bus.send(another_msg)
    """

    def __init__(self, name=None):
        self._q_f = None # feed
        self._q = None
        self.name = name

    @property
    @asynccontextmanager
    async def ctx(self):
        yield self

    async def send(self, msg:BusMessage, prio:int=0):
        raise RuntimeError("Override @send!")

    def __aiter__(self):
        raise RuntimeError("Override @__aiter__!")

    def __anext__(self):
        raise RuntimeError("Override @__anext__!")
