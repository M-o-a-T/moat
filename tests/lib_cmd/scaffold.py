from __future__ import annotations
import anyio
from moat.lib.cmd.base import MsgSender,MsgHandler, MsgLink
from moat.lib.cmd.msg import Msg
from moat.lib.cmd.stream import StreamHandler
from moat.util import Path
from contextlib import asynccontextmanager
import logging

logger = logging.getLogger(__name__)

def res_akw(a,kw):
    sa = "-" if not a else "|".join((str(x) if isinstance(x,Path) else repr(x)) for x in a)
    sk = "-" if not kw else "|".join(f"{k}={v!r}" for k,v in kw.items())
    return sa+" "+sk

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from moat.lib.cmd.msg import Msg

class LogLink(MsgLink):
    def __init__(self, rem:MsgLink, s: str):
        self._s = s
        self._rem = rem

    def ml_recv(self, a:list, kw:dict, flags:int) -> None:
        logger.debug("T:%s %s %d", self._s, res_akw(a,kw), flags)
        self._remote.ml_recv(a,kw,flags)


if False:
    class SimpleLinkMsg(Msg):
        def __init__(self, real:Msg, s: str):
            super().__init__(real.cmd,real,args,real.kw)
            assert real._remote is not None
            self._remote = real
            real._remote = self
            logger.debug("C:%s %s", self.__s, res_akw(real.args,real.kw))
            self.__s = s

        def emplace(self, remote: MsgLink):
            raise RuntimeError("Should not happen")

        def set_remote(self, remote: MsgLink):
            raise RuntimeError("Should not happen")

        def result(self,*a,**kw):
            logger.debug("R:%s %s", self.__s, res_akw(a,kw))
            self.__real.result(*a,**kw)


class StreamLoop(StreamHandler):
    __other:StreamLoop=None
    def __init__(self,h:MsgHandler,s:str):
        super().__init__(h)
        self.__s = s

    def attach_remote(self, other):
        self.__other = other

    async def __send(self):
        while True:
            msg = await self.msg_out()
            logger.warning("%s: %r", self.__s,msg)
            self.__other.msg_in(msg)

    @asynccontextmanager
    async def _ctx(self):
        async with super()._ctx():
            self.start(self.__send)
            yield self
            if not self.is_idle:
                logger.debug("NOT IDLE")
                while not self.is_idle:
                    await anyio.sleep(0.1)
                logger.debug("NOW IDLE")
            assert self.is_idle


@asynccontextmanager
async def scaffold(ha, hb, key=""):
    a = StreamLoop(ha,"A")
    b = StreamLoop(hb,"B")
    a.attach_remote(b)
    b.attach_remote(a)
    async with a,b:
        yield MsgSender(a), MsgSender(b)
    #assert not a._msgs, a._msgs
    #assert not b._msgs, b._msgs
