from __future__ import annotations

import anyio
from concurrent.futures import CancelledError

from moat.lib.micro import Event, L, TaskGroup, log, sleep_ms, wait_for
from moat.lib.path import Path
from moat.lib.proxy import as_proxy
from moat.lib.rpc import BaseCmd, BaseMsgHandler, MsgSender

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.util import attrdict
    from moat.lib.path import PathElem
    from moat.lib.rpc import BaseCmdMsg, Msg

    from collections.abc import Awaitable


class AuthError(RuntimeError):
    pass

VERS_MIN=1
VERS_MAX=1

class AuthNoRemote(AuthError):
    "Remote side doesn't support the auth protocol"

@as_proxy("_AuD")
class AuthDenied(AuthError):
    "Auth Denied"

@as_proxy("_AuV")
class AuthVersion(AuthError):
    "Auth version mismatch"

@as_proxy("_AuC")
class AuthClientServer(AuthError):
    "Protocol role clash"

@as_proxy("_AuR")
class AuthReject(AuthError):
    "Some auth method didn't work. Non-fatal."


class Auth(BaseMsgHandler):
    """
    Handle authorization.

    This is a mix-in class for `BaseCmdMsg`.
    """

    parent: BaseCmdMsg
    modes: dict[str, SubAuth]  # our SubAuth instances
    base_root: MsgSender  # dest for local commands; cfg.path gets added to this
    tg: TaskGroup | None = None
    auth: attrdict | None
    is_server: bool
    ok: Exception | SubAuth | None = None

    _auth_root: BaseMsgHandler
    _auth_done: Event

    def __init__(self, cfg: dict, parent: BaseCmdMsg):
        # super().__init__(cfg)
        self.cfg = cfg
        self.parent = parent
        self.auth = parent.auth
        self.is_server = parent.is_server
        self._auth_root = None
        self._auth_done = Event()

    def auth_done(self, root: BaseMsgHandler):
        self._auth_done.set()
        self._auth_done = None
        self._auth_root = root

    async def wait_done(self):
        "wait for auth completion"
        if self._auth_done is not None:
            await self._auth_done.wait()

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
        a_in = AuthCmdIn(self)
        async with TaskGroup() as tg:
            started = Event()

            async def run_auth():
                async with a_in:
                    started.set()
                    if not L:
                        await sleep_ms(50)
                    await a_in.task()
                    # Keep the auth handler context alive while parent.process()
                    # continues to route traffic through it after auth completes.
                    await anyio.sleep_forever()

            tg.start_soon(run_auth)
            await started.wait()
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
        await self.parent.check_rdy(msg, rcmd)

        if self._auth_done is not None:
            await self._auth_done.wait()
        if self._auth_root is None:
            raise AuthDenied("No auth")

        await self.parent.handle(msg, rcmd, _auth=True)


class _WithAuth(BaseMsgHandler):
    "Adds _auth to the handler call"

    def __init__(self, wrapped: BaseCmdMsg):
        self.wrapped = wrapped

    async def handle(self, msg: Msg, rcmd: list[PathElem]) -> Awaitable[None]:
        "Call the wrapped handler when it's ready"
        if L:
            await self.wrapped.wait_ready()
        await self.wrapped.handle(msg, rcmd, _auth=True)

    def find_handler(self, path, cmd: bool = False):
        "Stub to force using this object's ``handle`` method"
        cmd  # noqa:B018
        return self, path


class AuthCmdIn(BaseCmd):
    """Handles the incoming-message side of the auth protocol."""

    parent: Auth
    msg_in:Event|Msg
    msg_out:Event|tuple[list,dict]
    p_version:int  # protocol version

    def __init__(self, parent: Auth):
        self.parent = parent
        self.msg_in = Event()
        self.msg_out = Event()
        super().__init__(parent.cfg)

    async def _run(self, s_a: SubAuth):
        timeout = self.cfg.get("timeout")
        if not timeout:
            return await s_a.run()
        try:
            await wait_for(timeout, s_a.run)
        except TimeoutError:
            log("Timeout: %s(%s)", s_a.cfg.mode, s_a.name)

    #   async def teardown(self):
    #       breakpoint()
    #       await super().teardown()

    async def _send_cmd(self, sdr:MsgSender):
        modes = { c.get("name", c.mode) for c in self.cfg.modes }
        cmd:BaseCmdMsg = self.parent.parent
        try:
            name = self.cfg.name
        except AttributeError:
            name = cmd.auth_name or "_anon"

        vers = self.p_version or VERS_MAX
        try:
            res = await sdr.cmd(P(":n"), vers,
                            self.parent.is_server,name, modes, **cmd.auth_data_out())
        except AuthVersionError as err:
            vers = err.args
            if vers[1] < VERS_MIN or vers[0] > VERS_MAX:
                raise
            if self.p_version is not None:
                vers = min(vers,self.p_version)
            self.p_version = vers
            res = await sdr.cmd(P(":n"), vers,
                            self.parent.is_server,name, modes, **cmd.auth_data_out())
        except KeyError:
            raise AuthNoRemote
            
        if len(res) != 0:
            log("AuthResIn ??: %r", res.args)
        cmd.auth_data_res_in(min(vers,self.p_version), res.kw)

    async def task(self) -> MsgSender:
        raise RuntimeError("Owch Again")
        try:
            async with ungroup,TaskGroup() as tg:
                self.parent.tg = tg
                sdr = MsgSender(_WithAuth(self.parent.parent))
                self.modes = {}
                tg.start_soon(self._send_cmd, sdr)

                await self.msg_in.wait()
                modes = set(self.msg_in[3])

                for idx, cfg in enumerate(self.cfg.modes):
                    name = cfg.get("name", cfg.mode)
                    if name in self.modes:
                        raise ValueError(f"Duplicate mode {cfg.mode} for {self.path}")
                    if name not in modes:
                        continue  # not accepted by the other side

                    sub = get_auth(cfg.mode)(
                        cfg,
                        self.parent.auth.get(name),
                        self.parent,
                        idx,
                        name,
                        sdr.sub_at(Path.build((None, cfg.mode))),
                    )
                    self.modes[name] = sub

                    tg.start_soon(self._run, sub)

        except AuthNoRemote:
            if "none" in self.modes:
                self.parent.auth_done(self.modes["none"])
                return
            raise

        if L:
            self.set_ready()

        del self.modes  # no longer needed

        ok = self.parent.ok
        if ok is None:
            ok = AuthDenied("No auth method worked.")

        # don't yield from here on
        self.msg_out.set()
        self.msg_out = ok

        if isinstance(ok, Exception):
            # forward the exception to the remote side
            self.parent.auth_done(None)
        else:
            p = ok.cfg.get("path")
            sdr = self.parent.base_root.sender
            if p:
                sdr = sdr.sub_at(p)
            self.parent.auth_done(sdr)
        # don't yield before here!


    async def _handle_cmd(self, msg:Msg):
        """
        Remote call.
        """
        if not isinstance(self.msg_in,Event):
            raise ValueError("Duplicate")

        cmd = self.parent.parent
        self.p_version = msg[0]
        if not (VERS_MIN <= self.p_version <= VERS_MAX):
            raise AuthVersion(VERS_MIN,VERS_MAX)
        if msg[1] is not None and self.parent.is_server is msg[1]:
            raise AuthClientServer

        self.msg_in.set()
        self.msg_in = msg
        cmd.auth_data_in(msg.args, msg.kw)

        if not isinstance(self.msg_out,Event):
            raise ValueError("AlreadySent")
        await self.msg_out.wait()
        if isinstance(self.parent.ok, Exception):
            raise self.parent.ok  # will be forwarded to the remote side
        await msg.result(self.parent.ok.name, **cmd.auth_data_res_out())


    async def handle(self, msg: Msg, rcmd: list[PathElem]):
        """Handler for incoming messages"""
        if len(rcmd) and rcmd[-1] is None:
            if len(rcmd) == 1:
                return await msg.call_stream(self._handle_cmd)
            rcmd.pop()
            name = rcmd.pop()
            return await self.modes[name].handle(msg, rcmd)

        pad = self.parent._auth_done  # noqa:SLF001
        if pad is not None:
            await pad.wait()

        pa = self.parent._auth_root  # noqa:SLF001
        if pa is None:
            raise AuthDenied("No auth")
        return await pa.handle(msg, rcmd)


class SubAuth(BaseCmd):
    "base class for individual auth methods"

    def __init__(
        self,
        cfg: dict,
        auth: dict | None,
        parent: AuthCmdIn,
        idx: int,
        name: str,
        remote: MsgSender,
    ):
        super().__init__(cfg)
        self.idx = idx
        self.name = name
        self.parent = parent
        self.remote = remote
        self.auth = auth or {}
        self.is_server = parent.parent.is_server

    async def task(self):
        """Handle this auth method."""
        if L:
            self.set_ready()

        # This example is a no-op.
        return

    def accept(self):
        "Success. Forwarded to parent."
        self.parent.accept(self)

    def deny(self):
        "Rejection. Forwarded to parent."
        self.parent.deny(self)


def get_auth(mode: str) -> SubAuth:
    """
    Loads and initializes the named sub-auth.
    """
    from moat.util import import_  # noqa: PLC0415

    if "." not in mode:
        mode = "moat.lib.rpc.auth." + mode
    return import_(mode).SubAuth
