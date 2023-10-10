"""
Apps used for structure.
"""

from __future__ import annotations

from moat.micro.cmd.tree import BaseDirCmd, BaseFwdCmd
from moat.micro.cmd.base import BaseCmd

from moat.micro.compat import log, ExceptionGroup, BaseExceptionGroup
from moat.util import exc_iter 

class Tree(BaseDirCmd):
    """
    Structured subcommands.
    """
    pass

class Err(BaseFwdCmd):
    """
    An error catcher and subcommand manager.
    """
    async def run_app(self):
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
                return
            if len(b.exceptions) == 1:
                raise b.exceptions[0]
            raise
