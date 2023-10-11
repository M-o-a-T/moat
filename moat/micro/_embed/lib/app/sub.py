"""
Apps used for structure.
"""

from __future__ import annotations

from moat.micro.cmd.tree import BaseDirCmd, BaseFwdCmd
from moat.micro.cmd.base import BaseCmd

from moat.micro.compat import log, ExceptionGroup, BaseExceptionGroup, sleep_ms
from moat.util import exc_iter 

class Tree(BaseDirCmd):
    """
    Structured subcommands.
    """
    pass

class Err(BaseFwdCmd):
    """
    An error catcher and possibly-retrying subcommand manager.
    """
    async def wait_ready(self):
        await self._ready.wait()
        if self._wait:
            await super().wait_ready()

    async def dispatch(self, *a, **k):
        await self.app.wait_ready()
        return await super().dispatch(*a, **k)

    async def run_app(self):
        r = self.cfg.get("retry",0)
        t = self.cfg.get("timeout",100)
        self._wait = self.cfg.get("wait",True)
        self._ready.set()
        while True:
            try:
                await super().run_app()
            except Exception as exc:
                log("died %r", exc)
            except BaseExceptionGroup as exc:
                a,b = exc.split(ExceptionGroup)
                if a:
                    log("died %r", a)
                if not b:
                    log("???",err=exc)
                    break
                if len(b.exceptions) == 1:
                    raise b.exceptions[0]
                raise
            if not r:
                break
            if r > 0:
                r -= 1
            await sleep_ms(t)
            
            
