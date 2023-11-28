"""
Command tree support for MoaT commands
"""

from __future__ import annotations

from functools import partial

from moat.util import Path, import_
from moat.micro.compat import AC_use, Event, TaskGroup, log

from moat.micro.cmd.base import ACM_h, BaseCmd, ShortCommandError
from .dir import BaseSuperCmd

# Typing

from typing import TYPE_CHECKING  # isort:skip

if TYPE_CHECKING:
    from typing import AsyncContextManager, Awaitable, Never

    from moat.micro.proto.stack import BaseBuf, BaseMsg
    from moat.micro.stacks.util import BaseConnIter


class BaseLayerCmd(BaseSuperCmd):
    """
    A handler for a single nested app.

    This handler doesn't affect the command hierarchy.
    Its own commands, if any, are reachable by adding "_f" to their name.

    Alternately, the nested app is named "_".

    You need to override "gen_cmd" to create the app object.
    """

    app = None
    name = "_"

    async def run_app(self):
        """
        The command handler's executor. By default, calls `self.app.run`
        within the command's context.

        You might override this e.g. for restarting or
        shielding the rest of MoaT from errors.
        """
        await self.app.run()

    async def task(self):
        """
        Run the app as a subtask.

        You typically don't override this.
        """
        async with TaskGroup() as tg:
            if self.app is not None:
                await tg.spawn(self.run_app)
            await self.app.wait_ready()
            self.set_ready()

            # await self.app.stopped()
            # the return from the taskgroup already does that

    async def setup(self):
        await super().setup()
        self.app = await self.gen_cmd()
        if self.app is not None:
            self.app.attached(self, self.name)
            self.set_ready()

    async def reload(self):
        await super().reload()
        if self.app is not None:
            await self.app.reload()

    async def wait_ready(self, wait=True):
        if await super().wait_ready(wait=wait):
            return True
        if self.app is None:
            return None
        return await self.app.wait_ready(wait=wait)

    async def gen_cmd(self) -> BaseCmd:
        """
        Create the actual app to use.

        The default uses `None` and leaves the setup to `task`.
        """
        return None

    async def dispatch(self, action, msg, **kw):
        """
        Forward to the sub-app unless specifically directed not to.
        """
        if action and action[0][0] == "!":
            action = tuple(action[0][1:], *action[1:])
            return await super().dispatch(action, msg, **kw)

        await self.wait_ready()
        return await self.app.dispatch(action, msg, **kw)

    def set_ready(self):
        if self.app is None:
            raise RuntimeError("early")
        super().set_ready()

    def __getattr__(self, k):
        if k.startswith("_"):
            raise AttributeError(k)
        if k.endswith("_f"):
            return getattr(self, k[:-2])
        return getattr(self.app, k)


class BaseFwdCmd(BaseLayerCmd):
    """
    A handler for a single nested app that's configured locally.
    """

    async def gen_cmd(self):
        """
        Create the underlying app object
        """
        if self.root.APP is None:
            raise RuntimeError("WhereApp")
        gcfg = self.cfg
        name = gcfg.get("app", None)
        cfg = gcfg.get("cfg", {})
        log("Setup %s: %s", self.path, name)

        if name is None:
            if self.app is not None:
                self.app.stop()
                self.app = None
            return

        def imp(name):
            return import_(f"{self.root.APP}.{name}", 1)

        return imp(name)(cfg)
