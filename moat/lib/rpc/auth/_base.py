from __future__ import annotations

import anyio
from concurrent.futures import CancelledError

from moat.util import ungroup
from moat.lib.micro import ACM, AC_exit, Event, L, TaskGroup, log, sleep_ms, wait_for
from moat.lib.path import P, Path
from moat.lib.proxy import as_proxy
from moat.lib.rpc import BaseCmd, BaseMsgHandler, MsgSender

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from moat.util import attrdict
    from moat.lib.micro import _TaskGroupProto as _TaskGroupType
    from moat.lib.path import PathElem
    from moat.lib.rpc import BaseCmdMsg, Msg

    from typing import Protocol

    class _SubAuthType(Protocol):
        idx: int
        name: str
        cfg: attrdict

        async def handle(self, msg: Msg, rcmd: list[PathElem], *prefix: str) -> None: ...

        async def run(self) -> None: ...

    class _SubAuthFactory(Protocol):
        def __call__(
            self,
            cfg: attrdict,
            auth: dict | None,
            parent: AuthCmdIn,
            idx: int,
            name: str,
            remote: MsgSender,
        ) -> _SubAuthType: ...

else:
    _TaskGroupType = object
    _SubAuthType = object
    _SubAuthFactory = object


class AuthError(RuntimeError):
    pass


VERS_MIN = 1
VERS_MAX = 1


class AuthNoRemote(AuthError):
    "Remote side doesn't support the auth protocol"


@as_proxy("_AuD")
class AuthDenied(AuthError):
    "Auth Denied"


@as_proxy("_AuV")
class AuthVersionError(AuthError):
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

    This is a support class for {py:cls}`~moat.lib.stream.BaseCmdMsg`.
    """

    cfg: attrdict
    parent: BaseCmdMsg
    modes: dict[str, object]  # our auth instances
    base_root: MsgSender  # dest for local commands; cfg.path gets added to this
    tg: object | None = None
    auth: attrdict | None
    is_server: bool
    ok: Exception | object | None = None

    _auth_root: BaseMsgHandler | None
    _auth_done: Event | None

    def __init__(self, cfg: attrdict, parent: BaseCmdMsg):
        # super().__init__(cfg)
        self.cfg = cfg
        self.parent = parent
        self.auth = parent.auth
        self.is_server = parent.is_server
        self._auth_root = None
        self._auth_done = Event()

    def auth_done(self, root: BaseMsgHandler | None):
        if self._auth_done is not None:
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
            cast(_TaskGroupType, self.tg).cancel()
        self._auth_root = root

    async def process(self, root: MsgSender):
        """Run the auth handler, then the normal stream."""
        self.base_root = root
        a_in = AuthCmdIn(self)

        class _ProcAC:
            pass

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

            # ``parent.process`` opens transport contexts via ``CmdMsg.stream``.
            # Those must not attach to the command object's lifetime here,
            # because that would make them outlive this auth taskgroup and
            # break nursery LIFO order on cancellation.
            ac = _ProcAC()
            ACM(ac)
            self.parent.stream_owner_obj_ = ac
            try:
                await self.parent.process(a_in)
            except BaseException as exc:
                await AC_exit(ac, type(exc), exc, getattr(exc, "__traceback__", None))
                raise
            else:
                await AC_exit(ac)
            finally:
                del self.parent.stream_owner_obj_

    def accept(self, by: object):
        by = cast(_SubAuthType, by)
        if isinstance(self.ok, Exception):
            return  # too late

        if self.ok is None or cast(_SubAuthType, self.ok).idx > by.idx:
            self.ok = by

    def deny(self, by: object):
        by = cast(_SubAuthType, by)
        self.ok = AuthDenied(self.cfg.modes[by.idx].mode)
        if self.tg is not None:
            cast(_TaskGroupType, self.tg).cancel()

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

    async def handle(self, msg: Msg, rcmd: list[PathElem]) -> None:
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

    cfg: attrdict
    parent: Auth
    msg_in: Event | Msg
    msg_out: Event | Exception | object
    p_version: int | None = None  # protocol version

    def __init__(self, parent: Auth):
        self.parent = parent
        self.msg_in = Event()
        self.msg_out = Event()
        super().__init__(parent.cfg)

    async def _run(self, s_a: object):
        s_a = cast(_SubAuthType, s_a)
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

    async def _send_cmd(self, sdr: MsgSender):
        modes = {c.get("name", c.mode) for c in self.cfg.modes}
        cmd: BaseCmdMsg = self.parent.parent
        try:
            name = self.cfg.name
        except AttributeError:
            name = cmd.auth_name or "_anon"

        vers = self.p_version or VERS_MAX
        try:
            res = await sdr.cmd(
                P(":n"), vers, self.parent.is_server, name, modes, **cmd.auth_data_out()
            )
        except AuthVersionError as err:
            v_min, v_max = err.args
            if v_max < VERS_MIN or v_min > VERS_MAX:
                raise
            if self.p_version is not None:
                v_max = min(v_max, self.p_version)
            self.p_version = v_max
            res = await sdr.cmd(
                Path.build((None,)),
                v_max,
                self.parent.is_server,
                name,
                modes,
                **cmd.auth_data_out(),
            )
        except KeyError:
            raise AuthNoRemote from None

        if len(res) != 1:
            log("AuthResIn ??: %r", res.args)
        cmd.auth_data_res_in(res[0], res.kw)

    async def task(self) -> None:
        try:
            async with ungroup, TaskGroup() as tg_send:
                sdr = MsgSender(_WithAuth(self.parent.parent))
                self.modes = {}

                async def _send_cmd() -> None:
                    await self._send_cmd(sdr)

                await tg_send.spawn(_send_cmd)

                async with TaskGroup() as tg:
                    self.parent.tg = tg
                    try:
                        msg_in = self.msg_in
                        if isinstance(msg_in, Event):
                            await msg_in.wait()
                            msg_in = self.msg_in
                        if isinstance(msg_in, Event):
                            raise RuntimeError("No auth request")  # noqa:TRY004
                        modes = set(msg_in[3])

                        for idx, cfg in enumerate(self.cfg.modes):
                            name = cfg.get("name", cfg.mode)
                            if name in self.modes:
                                raise ValueError(f"Duplicate mode {cfg.mode} for {self.path}")
                            if name not in modes:
                                continue  # not accepted by the other side

                            sub = cast(_SubAuthFactory, get_auth(cfg.mode))(
                                cfg,
                                None if self.parent.auth is None else self.parent.auth.get(name),
                                self,
                                idx,
                                name,
                                cast(MsgSender, sdr.sub_at(Path.build((None, cfg.mode)))),
                            )
                            self.modes[name] = sub

                            async def _run_sub(sub: object = sub) -> None:
                                await self._run(sub)

                            tg.start_soon(_run_sub)
                    finally:
                        self.parent.tg = None

                if L:
                    self.set_ready()

                del self.modes  # no longer needed

                ok = self.parent.ok
                if ok is None:
                    ok = AuthDenied("No auth method worked.")
                    self.parent.ok = ok

                # Unblock the remote ``:n`` reply before waiting for ``_send_cmd``
                # to finish when ``tg_send`` exits.
                if not isinstance(self.msg_out, Event):
                    raise RuntimeError("AlreadySent")  # noqa:TRY004
                self.msg_out.set()
                self.msg_out = ok

                if isinstance(ok, Exception):
                    # forward the exception to the remote side
                    self.parent.auth_done(None)
                else:
                    ok = cast(_SubAuthType, ok)
                    p = ok.cfg.get("path")
                    sdr = self.parent.base_root.sender
                    if p:
                        sdr = cast(MsgSender, sdr.sub_at(p))
                    self.parent.auth_done(sdr)

        except AuthNoRemote:
            cmd = self.parent.parent
            cmd.auth_skip()
            if L:
                self.set_ready()
            del self.modes
            self.parent.auth_done(self.parent.base_root)
            return
        # don't yield before here!

    async def _handle_cmd(self, msg: Msg):
        """
        Remote call.
        """
        if not isinstance(self.msg_in, Event):
            raise RuntimeError("Duplicate")  # noqa:TRY004

        cmd = self.parent.parent
        self.p_version = msg[0]
        if not (VERS_MIN <= self.p_version <= VERS_MAX):
            raise AuthVersionError(VERS_MIN, VERS_MAX)
        if msg[1] is not None and self.parent.is_server is msg[1]:
            raise AuthClientServer

        self.msg_in.set()
        self.msg_in = msg
        cmd.auth_data_in(msg.args, msg.kw)

        if not isinstance(self.msg_out, Event):
            raise RuntimeError("AlreadySent")  # noqa:TRY004
        await self.msg_out.wait()
        if isinstance(self.parent.ok, Exception):
            raise self.parent.ok  # will be forwarded to the remote side
        ok = self.parent.ok
        if ok is None:
            raise AuthDenied("No auth")
        ok = cast(_SubAuthType, ok)
        await msg.result(ok.name, **cmd.auth_data_res_out(ok.name))

    def accept(self, by: object) -> None:
        """Forward auth acceptance to the parent controller."""
        self.parent.accept(by)

    def deny(self, by: object) -> None:
        """Forward auth rejection to the parent controller."""
        self.parent.deny(by)

    async def handle(self, msg: Msg, rcmd: list[PathElem], *prefix: str):
        """Handler for incoming messages"""
        prefix  # noqa:B018
        if len(rcmd) and rcmd[-1] is None:
            if len(rcmd) == 1:
                return await msg.call_stream(self._handle_cmd)
            rcmd.pop()
            name = rcmd.pop()
            return await cast(_SubAuthType, self.modes[name]).handle(msg, rcmd)

        pad = self.parent._auth_done  # noqa:SLF001
        if pad is not None:
            await pad.wait()

        pa = self.parent._auth_root  # noqa:SLF001
        if pa is None:
            raise AuthDenied("No auth")
        return await pa.handle(msg, rcmd)


class SubAuth(BaseCmd):
    "base class for individual auth methods"

    cfg: attrdict
    parent: AuthCmdIn
    remote: MsgSender

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


def get_auth(mode: str) -> object:
    """
    Loads and initializes the named sub-auth.
    """
    from moat.util import import_  # noqa: PLC0415

    if "." not in mode:
        mode = "moat.lib.rpc.auth." + mode
    return import_(mode).SubAuth
