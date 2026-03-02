"""
Authenticated nested RPC app.
"""

from __future__ import annotations

import sys

from moat.lib.micro import Event, L
from moat.lib.path import Path
from moat.lib.rpc import Auth, BaseSubCmd, DirCmd, MsgHandler, MsgSender
from moat.lib.rpc.auth._base import AuthDenied
from moat.lib.rpc.nest import CmdStream

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from moat.util import attrdict
    from moat.lib.path import PathElem
    from moat.lib.rpc import BaseCmdMsg, Msg

    from collections.abc import Awaitable, Callable


class _SecuredSubRoot(MsgHandler):
    """
    Internal root that exposes this command's sub-apps.
    """

    def __init__(self, parent: Cmd):
        self.parent = parent

    async def handle(self, msg: Msg, rcmd: list[PathElem]):
        if not rcmd:
            raise KeyError(msg.cmd)
        scmd = rcmd.pop()
        sub = BaseSubCmd.find_sub(self.parent, scmd)
        if sub is None:
            raise KeyError(scmd)
        sub_h = cast(
            "Callable[[Msg, list[PathElem]], Awaitable[object]]",
            getattr(sub, "handle", sub),
        )
        return await sub_h(msg, rcmd)


class _AuthBridge:
    """
    Run RPC auth on top of a nested command stream.
    """

    auth_name: str | None = None

    def __init__(
        self,
        cfg: attrdict,
        msg: Msg,
        *,
        is_server: bool,
        require_remote_auth: bool,
        debug: str | None = None,
    ):
        self.cfg = cfg
        self.msg = msg
        self.is_server = is_server
        self.require_remote_auth = require_remote_auth
        self.debug = debug

        self.auth = None
        if "auth" in cfg:
            from moat.util import attrdict as ad  # noqa: PLC0415

            self.auth = ad()
            if "pytest" in sys.modules:
                tcfg = cfg.auth.get("test", None)
                if tcfg is not None:
                    self.auth.update(tcfg)

        self._auth = Auth(cfg.auth, cast("BaseCmdMsg", self))
        self._stream = None
        self._ready = Event()

    async def run(self, root: MsgSender):
        """Run auth and nested command forwarding."""
        await self._auth.process(root)

    async def process(self, root: MsgHandler):
        """Run the nested RPC stream."""
        try:
            async with CmdStream(root, self.msg, debug=self.debug) as stream:
                self._stream = stream
                self._ready.set()
                await stream.reader_done.wait()
        finally:
            self._stream = None

    async def check_rdy(self, msg: Msg, rcmd: list[PathElem]):
        "Auth helper hook."
        msg  # noqa: B018
        rcmd  # noqa: B018

    def auth_data_out(self) -> dict:
        "Auth helper hook."
        return {}

    def auth_data_in(self, args, data) -> None:
        "Auth helper hook."
        args  # noqa: B018
        data  # noqa: B018

    def auth_data_res_out(self, role: str) -> dict:
        "Auth helper hook."
        role  # noqa: B018
        return {}

    def auth_data_res_in(self, role: str, data) -> None:
        "Auth helper hook."
        role  # noqa: B018
        data  # noqa: B018

    def auth_skip(self) -> None:
        "Reject unauthenticated peers for this app."
        if self.require_remote_auth:
            raise AuthDenied("Auth required")

    async def wait_ready(self, wait=True):
        """Auth helper hook used by :class:`moat.lib.rpc.auth._base._WithAuth`."""
        if self._stream is None:
            if wait:
                await self._ready.wait()
                return False
            return None
        return False

    async def handle(self, msg: Msg, rcmd: list[PathElem], _auth: bool = False):
        """Forward a call to the nested stream, with auth if configured."""
        if not _auth:
            return await self._auth.handle(msg, rcmd)
        await self._ready.wait()
        if self._stream is None:
            raise EOFError
        return await self._stream.handle(msg, rcmd)


class Cmd(DirCmd):
    """
    Expose a protected subtree via a single authenticated stream.

    Configuration:

    - ``auth``: authentication configuration.
    - ``path``: optional path to a pre-existing subtree.
    - Otherwise, local sub-apps are defined by normal ``DirCmd`` style entries.
    """

    doc = dict(
        _c=dict(
            _d="secured nested RPC stream",
            auth="dict:auth config",
            path="path:forward to this subtree",
            _n="app:sub-app",
        )
    )

    _target_path: Path | None = None
    _sub_root: _SecuredSubRoot | None = None

    async def setup(self):
        """Validate configuration before startup."""
        await super().setup()
        if "auth" not in self.cfg:
            raise ValueError(f"{self.path}: Missing auth configuration")

        local_apps = False
        for value in self.cfg.values():
            try:
                if value.get("running", True) and isinstance(value.get("app", None), str):
                    local_apps = True
                    break
            except AttributeError:
                continue

        path = self.cfg.get("path", None)
        if path is not None:
            self._target_path = Path.build(path)
            if local_apps:
                raise ValueError(f"{self.path}: can't combine 'path' with local app entries")
        else:
            if not local_apps:
                raise ValueError(f"{self.path}: need either 'path' or local app entries")
            self._sub_root = _SecuredSubRoot(self)

    async def _setup_apps(self):
        """
        Setup sub-apps while ignoring non-app helper mappings.
        """
        from moat.lib.rpc import LoadCmd  # noqa: PLC0415

        gcfg = self.cfg
        root = self.root
        if root is None:
            raise RuntimeError("No root set")
        root.cfg_reloaded(gcfg)

        apps = {}
        for k, v in gcfg.items():
            if k in {"auth", "path", "debug"}:
                continue
            try:
                if not v.get("running", True):
                    continue
                nam = v.get("app", None)
                if not isinstance(nam, str):
                    continue
                apps[k] = v
            except AttributeError:
                continue

        for name in list(self.sub.keys()):
            if name not in apps:
                await self.detach(name)

        for name in apps:
            if name in self.sub:
                continue
            cfg = gcfg[name]
            await self.attach(name, LoadCmd(cfg))

        for app in self.sub.values():
            await self.start_app(app)

        if L:
            for app in self.sub.values():
                if app.cfg.get("wait", True):
                    await app.wait_ready()
            self.set_ready()

    def find_sub(self, scmd):  # noqa: D102
        scmd  # noqa: B018
        return None

    async def stream(self, msg: Msg):
        """Open the authenticated nested command stream."""
        if L:
            await self.wait_ready()
        root = self.root
        if root is None:
            raise RuntimeError("No root")

        if self._target_path is None:
            if self._sub_root is None:
                raise RuntimeError("No secured sub-root")
            target = MsgSender(self._sub_root)
        else:
            target = root.sender.sub_at(self._target_path)

        async with msg.stream():
            bridge = _AuthBridge(
                self.cfg,
                msg,
                is_server=True,
                require_remote_auth=True,
                debug="" if self.cfg.get("debug", False) else None,
            )
            await bridge.run(target)
