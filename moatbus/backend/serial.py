#
"""
Send bus messages to a Trio stream
"""

from anyio_serial import Serial
from contextlib import asynccontextmanager

from ..serial import SerBus
from ._stream import StreamHandler

class Handler(StreamHandler):
    """
    This class defines the interface for exchanging MoaT messages on a
    serial line.

    Usage::
        
        async with moatbus.backend.serial.Handler("/dev/ttyUSB1",115200) as bus:
            async for msg in bus:
                await process(msg)
    """
    short_help="Serial MoaT bus (P2P)"
    need_host = True

    PARAMS = {
        "port":(str,"Port to use", lambda x:len(x)>2, None, "too short"),
        "baudrate":(int,"Port speed", lambda x:1200<=x<=2000000, 115200, "must be between 1200 and 2MBit"),
        "tick":(float,"frame timeout", lambda x:0<x<1, 0.1,"must be between 0 and 1 second"),
    }

    def __init__(self, port:str, baudrate:int, tick:float=0.1):
        super().__init__(None,tick)
        self.port = port
        self.baudrate = baudrate

    @classmethod
    def repr(cls, cfg):
        return cfg["port"]

    @asynccontextmanager
    async def _ctx(self):
        async with Serial(port=self.port, baudrate=self.baudrate) as S:
            self._stream = S
            async with super()._ctx():
                yield self
