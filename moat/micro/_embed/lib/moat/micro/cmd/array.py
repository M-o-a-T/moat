"""
A command that accesses a row of mostly-identical subcommands
"""

from __future__ import annotations

from moat.util import combine_dict, import_
from moat.lib.cmd.base import MsgSender
from moat.lib.cmd.errors import ShortCommandError
from moat.lib.cmd.msg import Msg
from moat.lib.codec.errors import NoPathError
from moat.util.compat import L, TaskGroup

from .tree.dir import BaseSuperCmd
from .util.part import set_part

from typing import TYPE_CHECKING  # isort:skip

if TYPE_CHECKING:
    from collections.abc import Awaitable


class ArrayCmd(BaseSuperCmd):
    """
    A command that hosts a number of mostly-identical subcommands.
    """

    n: int = None

    def __init__(self, cfg):
        super().__init__(cfg)
        self.apps = []

    async def setup(self):  # noqa:D102
        await super().setup()
        await self._setup_apps()

    if L:

        async def wait_ready(self, wait=True):
            """Delay until this subtree is up,

            Returns True if any sub-apps are stopped.
            """
            await super().wait_ready(wait=wait)
            again = True
            res = False
            while again:
                again = False
                for app in self.apps:
                    if (w := await app.wait_ready(wait=wait)) is None:
                        if not wait:
                            return None
                        again = True
                        res = None
                    elif w is True:
                        return True
            return res

    async def attach(self, name, app) -> None:
        """
        Attach a sub-handler to me.

        An existing handler with this name is stopped.
        """
        try:
            oa = self.apps[name]
        except IndexError:
            if len(self.apps) != name:
                raise
            self.apps.append(app)
            oa = None
        else:
            self.apps[name] = app
        app.attached(self, name)
        if oa is not None:
            await oa.stop()

    def detach(self, name) -> Awaitable:
        """
        Detach and stop a command handler.
        """
        return self.attach(name, None)

    def _cfg(self, i):
        cfg = combine_dict(self.cfg.get("cfg", {}), self.cfg.get(i, {}))
        if (ii := self.cfg.get("i", None)) is not None:
            set_part(cfg, ii, i + self.cfg.get("i_off", 0))
        return cfg

    async def reload(self):  # noqa:D102
        await super().reload()
        self.n = self.cfg["n"]
        for i, app in enumerate(self.apps):
            app.cfg.merge(self._cfg(i))
            await app.reload()
        while len(self.apps) > self.n:
            app = self.apps.pop()
            await self.detach(len(self.apps))

    async def _setup_apps(self):
        name = self.cfg["app"]
        cls = import_(f"{self.root.APP}.{name}", 1)

        self.n = self.cfg["n"]
        for i in range(self.n):
            app = cls(self._cfg(i))
            await self.attach(i, app)

        for app in self.apps:
            await self.start_app(app)

    async def handle(self, msg, rcmd):
        """
        Dispatch a message to subcommands.

        See `BaseCmd.handle` for details.
        """

        if not rcmd:
            raise ShortCommandError(msg.cmd)
        if isinstance(rcmd[-1], str) and rcmd[-1][0] == "!":
            rcmd[-1] = rcmd[-1][1:]
            return await super().handle(msg, rcmd)

        cmd = rcmd.pop()
        if cmd == "all":
            if msg.can_stream:
                return await self._stream_all(msg, rcmd)
            else:
                return await self._cmd_all(msg, rcmd)

        try:
            sub = self.apps[cmd]
        except (TypeError, IndexError):
            raise NoPathError(
                self.path,
                msg.cmd,
                self.__class__.__name__,
                await self.cmd_dir_(v=None),
            ) from None
        return await sub.handle(msg, rcmd)

    doc_dir_ = dict(na="int:max index")

    async def cmd_dir_(self, **kw):
        "report max index"
        res = await super().cmd_dir_(**kw)
        res["na"] = len(self.apps)
        return res

    doc_all = dict(
        _d="apply to all",
        _0="path:command",
        _99="list:args",
        s="int:start index",
        e="int:end index",
    )

    async def _cmd_all(self, msg, rcmd):
        """
        Call all sub-apps and collect the result.
        """
        if rcmd:
            cmd = rcmd[:]
            cmd.reverse()
        else:
            cmd = msg.args_l.pop(0)
            if isinstance(cmd, str):
                cmd = [cmd]
            else:
                cmd = list(cmd)

        res = []
        snd = MsgSender(None)
        for app in self.apps:
            snd.set_root(app)
            r = await snd.cmd(cmd, *msg.args, *msg.kw)
            res.append((r.args, r.kw))
        await msg.result(*res)

    async def _stream_all(self, msg, rcmd):
        """
        Call all sub-apps and send the result.
        """
        if not rcmd:
            cmd = msg.args.pop(0)
            if isinstance(cmd, str):
                cmd = [cmd]
            else:
                cmd = list(cmd)
            cmd.reverse()
            rcmd = cmd

        async def _reply(i, app, st):
            msg_ = Msg.Call(msg.cmd, msg.args, msg.kw)
            res = await app.handle(msg_, rcmd[:])
            await st.send(i, *res.args, **res.kw)

        async with msg.stream_out() as st, TaskGroup() as tg:
            for i, app in enumerate(self.apps):
                tg.start_soon(_reply, i, app, st)

        await msg.result()
