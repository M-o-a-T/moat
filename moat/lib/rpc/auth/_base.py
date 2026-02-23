from __future__ import annotations

from moat.lib.micro import L, TaskGroup, log, wait_for
from moat.lib.path import Path
from moat.lib.proxy import as_proxy
from moat.lib.rpc import BaseCmd, CmdMsg, MsgSender

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.lib.path import PathElem
    from moat.lib.rpc import Msg


class AuthError(RuntimeError):
    pass


@as_proxy("_AuD")
class AuthDenied(AuthError):
    "Auth Denied"


@as_proxy("_AuR")
class AuthReject(AuthError):
    "Some auth method didn't work. Non-fatal."


class Auth(CmdMsg):
    modes: dict[str, SubAuth]

    async def _run(self, s_a: SubAuth):
        if not self.cfg.timeout:
            return await s_a.run()
        try:
            await wait_for(self.cfg.timeout, s_a.run)
        except TimeoutError:
            log("Timeout: %s(%d)", self.cfg.modes[s_a.idx].mode, s_a.idx)

    async def task(self):
        async with TaskGroup() as self.tg:
            sdr = MsgSender(self)
            self.modes = {}
            self.ok = None
            for cfg in self.cfg.modes:
                name = cfg.get("name", cfg.mode)
                if name in self.modes:
                    raise ValueError(f"Duplicate mode {cfg.mode} for {self.path}")
                sub = get_auth(cfg.mode)(cfg, self, name, sdr.sub_at(Path.build((None, cfg.mode))))
                self.modes[cfg.mode] = sub

                self.tg.start_soon(self._run, sub)

        if self.ok is None:
            self.ok = AuthDenied("No auth method worked.")

        if isinstance(self.ok, Exception):
            # forward the exception to the remote side
            await sdr.cmd((None,), self.ok)
            raise self.ok

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

    async def handle(self, msg: Msg, rcmd: list[PathElem], *prefix: list[str]):
        if prefix:
            raise RuntimeError("Prefix??")
        if len(rcmd) and rcmd[-1] is None:
            if len(rcmd) == 1:
                return await msg.call_simple(self._err)
            rcmd.pop()
            mode = rcmd.pop()
            return await self.modes[mode].handle(msg, rcmd)

        return await super().handle(msg, rcmd)


class SubAuth(BaseCmd):
    "base class for individual auth methods"

    def __init__(self, cfg: dict, parent, idx: int, remote: MsgSender):
        super().__init__(cfg)
        self.idx = idx
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
