from __future__ import annotations

from concurrent.futures import CancelledError

from moat.lib.micro import Event, L, TaskGroup, log, wait_for
from moat.lib.path import Path
from moat.lib.proxy import as_proxy
from moat.lib.rpc import BaseCmd, BaseMsgHandler, MsgSender

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.lib.path import PathElem
    from moat.lib.rpc import BaseCmdMsg, Msg

    from collections.abc import Awaitable


class AuthError(RuntimeError):
    pass


@as_proxy("_AuD")
class AuthDenied(AuthError):
    "Auth Denied"


@as_proxy("_AuR")
class AuthReject(AuthError):
    "Some auth method didn't work. Non-fatal."


class Auth:
    """
    Handle authorization.

    This is a mix-in class for `BaseCmdMsg`.
    """

    modes: dict[str, SubAuth]
    base_root: MsgSender  # dest for local commands; cfg.path gets added to this
    tg: TaskGroup | None = None

    _auth_root: BaseMsgHandler
    _auth_done: Event

    def __init__(self, cfg: dict, parent: BaseCmdMsg):
        # super().__init__(cfg)
        self.cfg = cfg
        self.parent = parent
        self._auth_root = None
        self._auth_done = Event()

    def auth_done(self, root: BaseMsgHandler):
        self._auth_done.set()
        self._auth_done = None
        self._auth_root = root
        if L:
            self.set_ready()

    def stop(self, root: BaseMsgHandler | None = None):
        """
        Interrupt the auth process.
        """
        if self.ok is None:
            self.ok = CancelledError()
        if self.tg is not None:
            self.tg.cancel()
        self._auth_root = root

    async def process(self, root: BaseMsgHandler):
        """Run the auth handler, then the normal stream."""
        self.base_root = root
        async with AuthCmdIn(self) as a_in:
            await self.parent.process(a_in)

    def accept(self, by: SubAuth):
        if isinstance(self.ok, Exception):
            return  # too late

        if self.ok is None or self.ok.idx > by.idx:
            self.ok = by

    def deny(self, by: SubAuth):
        self.ok = AuthDenied(self.cfg.modes[by.idx].mode)
        self.tg.cancel()

    async def _err(self, exc):
        "auth error from remote"
        if isinstance(exc, AuthReject):
            log("Rejected: %r", exc)
        else:
            raise exc

    async def handle(self, msg: Msg, rcmd: list[PathElem]):
        """Handler for outgoing messages"""
        await self.check_rdy(msg, rcmd)

        if self._auth_done is not None:
            await self._auth_done.wait()
        if self._auth_root is None:
            raise AuthDenied("No auth")

        await self.parent.handle(msg, rcmd, _auth=True)


class _WithAuth(BaseMsgHandler):
    "Adds _auth to the handler call"

    def __init__(self, wrapped: BaseCmdMsg):
        self.wrapped = wrapped

    def handle(self, msg: Msg, rcmd: list[PathElem]) -> Awaitable[None]:
        return self.wrapped.handle(msg, rcmd, _auth=True)


class AuthCmdIn(BaseCmd):
    """Handles the incoming-message side of the auth protocol."""

    def __init__(self, parent):
        self.parent = parent
        super().__init__(parent.cfg)

    async def _run(self, s_a: SubAuth):
        if not self.cfg.timeout:
            return await s_a.run()
        try:
            await wait_for(self.cfg.timeout, s_a.run)
        except TimeoutError:
            log("Timeout: %s(%d)", self.cfg.modes[s_a.name].mode, s_a.name)

    async def task(self) -> MsgSender:

        async with TaskGroup() as tg:
            self.parent.tg = tg
            sdr = MsgSender(_WithAuth(self.parent))
            self.modes = {}
            self.ok = None
            for idx, cfg in enumerate(self.cfg.modes):
                name = cfg.get("name", cfg.mode)
                if name in self.modes:
                    raise ValueError(f"Duplicate mode {cfg.mode} for {self.path}")
                sub = get_auth(cfg.mode)(
                    cfg, self, idx, name, sdr.sub_at(Path.build((None, cfg.mode)))
                )
                self.modes[name] = sub

                tg.start_soon(self._run, sub)

            if L:
                self.set_ready()

        if self.ok is None:
            self.ok = AuthDenied("No auth method worked.")

        if isinstance(self.ok, Exception):
            # forward the exception to the remote side
            await sdr.cmd((None,), self.ok)
            self.parent.auth_done(None)
            raise self.ok

        p = self.ok.cfg.get("path")
        sdr = self.parent.base_root.sender
        if p:
            sdr = sdr.sub_at(p)
        self.parent.auth_done(sdr)

    async def cmd_dir_(self, v: bool = True, **kw):
        "add auth methods"
        res = super().cmd_dir_(v=v, **kw)
        if v is not False:
            res["auth"] = list(self.modes.keys())
        return res

    async def handle(self, msg: Msg, rcmd: list[PathElem]):
        """Handler for incoming messages"""
        if len(rcmd) and rcmd[-1] is None:
            if len(rcmd) == 1:
                return await msg.call_simple(self._err)
            rcmd.pop()
            name = rcmd.pop()
            if name == "dir_":
                return await msg.call_simple(self.cmd_dir_)
            return await self.parent.modes[name].handle(msg, rcmd)

        pad = self.parent._auth_done  # noqa:SLF001
        if pad is not None:
            await pad.wait()

        pa = self.parent._auth_root  # noqa:SLF001
        if pa is None:
            raise AuthDenied("No auth")
        return await pa.handle(msg, rcmd)


class SubAuth(BaseCmd):
    "base class for individual auth methods"

    def __init__(self, cfg: dict, parent, idx: int, name: str, remote: MsgSender):
        super().__init__(cfg)
        self.idx = idx
        self.name = name
        self.parent = parent
        self.remote = remote

    async def task(self):
        """Handle this auth method."""
        if L:
            self.set_ready()

        # This example is a no-op.
        if not await self.remote():
            self.parent.deny(self)

        return

    async def cmd(self):
        """Handle receiving a request for this auth method"""
        return True


def get_auth(mode: str) -> SubAuth:
    """
    Loads and initializes the named sub-auth.
    """
    from moat.util import import_  # noqa: PLC0415

    if "." not in mode:
        mode = "moat.lib.rpc.auth." + mode
    return import_(mode).SubAuth
