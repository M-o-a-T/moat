from __future__ import annotations

import anyio
import time
from attrs import define, field
from contextlib import nullcontext, AsyncExitStack
from moat.link import protocol_version
from collections import deque
from moat.util import as_service, P, srepr, attrdict, NotGiven
from moat.util.times import humandelta
import logging

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import NoReturn
    from moat.link.client import Link

__all__ = ["ntfy_bridge"]

logger = logging.getLogger(__name__)

@define
class IDT:
    """
    This object holds a single link ID.
    """
    id = field(type=str)
    # ID

    up = field(type=bool|None,kw_only=True,default=None)
    # None: no link state seen, True: latest link state

    host = field(type=str,default=None,kw_only=True)
    # host name seen

    id_seen = field(type=bool,default=False,init=False)
    # flag whether ID message seen

    last = field(factory=time.time, init=False)
    # time of last Ping (or other message)
    
    def __str__(self):
        return srepr(dict(id=self.id,up=self.up,ids=self.id_seen,host=self.host,last=humandelta(time.time()-self.last)))


class Mon:
    """
    Monitor IDs (and the host entries that point to them).
    """
    debug=False
    def __init__(self, cfg:dict, link:Link):
        self.cfg = cfg
        self.link = link

        self._ids = {}
        self._idq = deque()

    async def run(self, debug=False, *, task_status=anyio.TASK_STATUS_IGNORED):
        self.debug=debug
        async with anyio.create_task_group() as tg:
            await tg.start(self._mon_ping)
            await tg.start(self._mon_id)
            await tg.start(self._mon_host)
            await tg.start(self._timer)
            task_status.started()

            while debug:
                await anyio.sleep(5)
                print("IDs:")
                for idt in self._ids.values():
                    print(idt)

    async def _timer(self, *, task_status=anyio.TASK_STATUS_IGNORED):
        # monitor _idq
        timeout = self.cfg.timeout.no_ping
        ping = self.cfg.timeout.ping
        task_status.started()
        while True:
            if not self._idq:
                # This should never happen except on startup, so ignore.
                await anyio.sleep(ping)
                continue

            while self._idq:
                t=time.time()
                tt,idt = self._idq.popleft()

                if tt+timeout > t:
                    await anyio.sleep(tt+timeout-t)
                if idt.up is False:
                    # already down
                    continue
                if tt+1<idt.last:
                    # new packet arrived
                    continue
                await self._cleanup(idt)

    async def _cleanup(self, idt:IDT):
        if self.debug:
            print("Clean",str(idt))

        if idt.up is False:
            return
        idt.up = False
        if idt.host is not None:
            await self.link.d_set(P("host")/idt.host, retain=True)
        if idt.id_seen:
            await self.link.d_set(P("run.id")/idt.id, retain=True)
        self._ids.pop(idt.id,None)

    async def _mon_ping(self, *, task_status=anyio.TASK_STATUS_IGNORED):
        # Monitor ping messages
        path=P("run.ping.id")
        async with self.link.d_watch(path, subtree=True, state=False) as mon:
            task_status.started()
            async for p,msg in mon:
                if len(p) != 1:
                    logger.warning("Mon %s: ?? %s", path+p, msg)
                    continue

                id=p[0]
                if self.debug:
                    print("PING",id,srepr(msg))

                if (idt := self._ids.get(id, None)) is not None:
                    if not msg.get("up"):
                        # going down
                        await self._cleanup(idt)
                        continue
                    # mark seen
                    idt.up = True
                    idt.last = time.time()
                else:
                    if not msg.get("up"):  # down anyway. Ignore.
                        continue
                    self._ids[id] = idt = IDT(id=id, up=True)

                self._idq.append((time.time(),idt))

    async def _mon_host(self, *, task_status=anyio.TASK_STATUS_IGNORED):
        path=P("host")
        async with self.link.d_watch(path, subtree=True, state=None) as mon:
            task_status.started()
            async for p,msg in mon:
                if len(p) != 1:
                    logger.warning("Mon_host %s: ?? %s", path+p, msg)
                    continue
                if msg is NotGiven:
                    continue

                host=p[0]
                id=msg["id"]
                if self.debug:
                    print("HOST",host,srepr(msg))

                if (idt := self._ids.get(id, None)) is None:
                    self._ids[id] = idt = IDT(id=id, up=None)
                elif idt.up is False:
                    idt.up = None  # owch?
                idt.host=host
                self._idq.append((time.time(),idt))

    async def _mon_id(self, *, task_status=anyio.TASK_STATUS_IGNORED):
        path=P("run.id")
        async with self.link.d_watch(path, subtree=True, state=None) as mon:
            task_status.started()
            async for p,msg in mon:
                if msg is NotGiven:
                    continue
                if len(p) != 1:
                    logger.warning("Mon_id %s: ?? %s", path+p, msg)
                    continue

                id=p[0]
                if self.debug:
                    print("ID",id,srepr(msg))

                if (idt := self._ids.get(id, None)) is None:
                    self._ids[id] = idt = IDT(id=id, up=None)
                elif idt.up is False:
                    idt.up = None  # owch?
                idt.id_seen=True
                self._idq.append((time.time(),idt))


async def cmd_host(link:Link, cfg:dict, main:bool=False, *, debug=False, task_status=anyio.TASK_STATUS_IGNORED) -> NoReturn:
    """
    Host specific runner.

    This command tells MoaT-Link that a particular host is up.
    """

    async with AsyncExitStack() as ex:
        if task_status is anyio.TASK_STATUS_IGNORED:
            srv = await ex.enter_async_context(as_service(attrdict(debug=debug)))
            tg = srv.tg
        else:
            srv = task_status
            tg = await ex.enter_async_context(anyio.create_task_group())

        await link.d_set(P("host")/link.name, dict(id=link.id), retain=True)
        if main:
            await srv.tg.start(Mon(cfg, link).run, debug)
        srv.started()

        await anyio.sleep_forever()
