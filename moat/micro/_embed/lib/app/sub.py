"""
Apps used for structure.
"""

from __future__ import annotations

from moat.micro.cmd.tree import DirCmd, BaseFwdCmd
from moat.micro.cmd.base import BaseCmd

from moat.micro.compat import log, ExceptionGroup, BaseExceptionGroup, sleep_ms
from moat.util import exc_iter 

class Tree(DirCmd):
    """
    Structured subcommands.
    """
    pass

class Err(BaseFwdCmd):
    """
    An error catcher and possibly-retrying subcommand manager.

    This catches errors
    """
    _wait = True

    async def dispatch(self, *a, **k):
        if self.app is None:
            await super().wait_ready()
        await self.app.wait_ready()
        return await super().dispatch(*a, **k)

    def set_ready(self):
        pass  # XXX ?

    async def run_app(self):
        log("Fwd Start %s", self.path)
        r = self.cfg.get("retry",0)
        t = self.cfg.get("timeout",100)
        a = self.cfg.get("always",False)

        self._wait = self.cfg.get("wait",True)
        # await self.set_ready()  ## TEST
        while True:
            err = None
            try:
                log("Fwd Run %s %r", self.path, self)
                await super().run_app()
            except OSError as exc:
                log("Fwd Err %s %r", self.path, exc)
                err = exc
            else:
                # ends without error
                log("Fwd End %s %r", self.path, self.app)
                if not a or not r:
                    return
            if not r:
                raise err
            if r > 0:
                r -= 1
            try:
                await sleep_ms(t)
            except BaseException as exc:
                log("Fwd ErrX %s %r", self.path, exc)
                raise
