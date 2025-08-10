from __future__ import annotations

import anyio
import time
from abc import ABCMeta, abstractmethod
from contextlib import AsyncExitStack, asynccontextmanager
from moat.link import protocol_version
from moat.util.misc import srepr
from moat.util import as_service, P, Path, attrdict, CtxObj
import logging

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import NoReturn
    from moat.link.client import Link

__all__ = ["ntfy_bridge"]

logger = logging.getLogger(__name__)

class Notify:
    def __init__(self, cfg):
        self.cfg = cfg

    async def run(self, link:Link):
        self.link = link
        async with AsyncExitStack() as ex:
            backend = self.cfg.backend
            if isinstance(backend,str):
                backend=(backend,)

            self._backends = {}
            for name in backend:
                cfg = self.cfg.get(name,attrdict())
                try:
                    notifier = await ex.enter_async_context(get_backend(name, link,cfg))
                except Exception as exc:
                    logger.warning("Backend %r", name, exc_info=exc)
                else:
                    self._backends[name] = notifier

            if not self._backends:
                raise RuntimeError("No backend worked.")

            try:
                await self._run()
            finally:
                with anyio.move_on_after(2, shield=True):
                    await self.send("error.notify",f"Backend stopped", "The backend terminated.", prio="fatal")


    async def send(self, *a, **kw) -> None:
        """Send this notification to that topic."""
        bad = []
        dropped = []
        for name,b_e in list(self._backends.items()):
            try:
                await b_e.send(*a,**kw)
            except Exception as exc:
                logger.warning("Backend %r", name, exc_info=exc)
                bad.append(b_e)

        for name in bad:
            if self._backends.pop(name,None) is not None:
                dropped.append(name)
        if not self._backends:
            raise RuntimeError("All backends failed.")

        for name in dropped:
            await self.send("error.notify",f"Backend {name} error", "The backend errored and was removed.", prio="error")


    async def _run(self) -> NoReturn:
        """
        A bridge that monitors the Notify subchannel and forwards to NTFY.SH
        (or a private server).
        """
        async with as_service(attrdict(debug=False)) as srv:
            try:
                await srv.tg.start(self._keepalive)

                async with self.link.d_watch(self.cfg.path,subtree=True,meta=True,state=None) as mon:
                    srv.set()
                    async for path,msg,meta in mon:
                        t = time.time()
                        if meta.timestamp < t-self.cfg.max_age:
                            continue
                        if isinstance(msg,dict):
                            if "title" not in msg:
                                title = str(path)
                            await self.send(topic=path, **msg)
                        else:
                            await self.send(topic=path, msg=str(msg))

                    # not reached, loop doesn't terminate

            except Exception as exc:
                await self.send(topic=P("error.notify"),
                    msg=repr(exc), prio="error",title="Gateway failure")
                raise


    async def _keepalive(self, *, task_status=anyio.TASK_STATUS_IGNORED) -> NoReturn:
        "Monitor the keepalive topic"
        bad = False
        link = self.link
        main_host = link.cfg.main
        keep = self.cfg.keepalive
        ok_keep = keep.ok

        timeout = keep.get("timeout",link.cfg.timeout.ping*1.5)

        async with link.d_watch(P("host")/main_host, state=None) as mon:
            task_status.started()
            mon = aiter(mon)
            while True:
                if bad:
                    msg = await anext(mon)
                else:
                    try:
                        with anyio.fail_after(timeout*2):
                            msg = await anext(mon)
                    except TimeoutError:
                        msg = None

                if isinstance(msg,dict) and "id" in msg:
                    async with link.d_watch(P("run.ping.id")/msg["id"]) as mon2:
                        mon2 = aiter(mon2)
                        while True:
                            try:
                                with anyio.fail_after(timeout):
                                    msg = await anext(mon2)
                                    if not msg.get("up", False):
                                        break
                                    if bad and "msg" in ok_keep:
                                        await self.send(topic="error.notify",**ok_keep)
                                        bad = False
                            except TimeoutError:
                                break

                res = await self.send(topic="error.notify", **keep)
                bad=True



def get_backend(name:str, link:Link, cfg: dict) -> Backend:
    """
    Fetch the backend named in the config and initialize it.
    """
    from importlib import import_module

    if "." not in name:
        name = "moat.link.notify." + name
    return import_module(name).Notifier(link,cfg)

class Notifier(CtxObj, metaclass=ABCMeta):
    "Base class for notification backends"

    def __init__(self, link:Link, cfg: attrdict):
        self.cfg = cfg
        self.link = link

    @asynccontextmanager
    async def _ctx(self) -> AsyncIterator[Self]:
        yield self

    @abstractmethod
    async def send(self, topic:str|Path, title:str, msg:str, **kw):
        """Send this notification to that topic."""
