"""
Bare-bones connection to a MoaT server
"""

from __future__ import annotations

import anyio
import logging

from attrs import define, field

from moat.util import attrdict
from moat.lib.path import P

from . import protocol_version as proto_version
from . import protocol_version_min as proto_version_min
from .common import CmdCommon

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.lib.path import PathElem
    from moat.lib.rpc import Key, Msg, MsgSender

    from .auth import AuthMethod

    from typing import Any

logger = logging.getLogger(__name__)


class NotAuthorized(RuntimeError):  # noqa: D101
    pass


def _to_dict(x: list[AuthMethod]) -> dict[str, AuthMethod]:
    return {a.name: a for a in x}


class _NoRPCAuth(RuntimeError):
    "Internal marker for falling back to legacy Hello/auth."


class _RPCRoot:
    "Minimal object exposing ``.sender`` for the RPC auth helper."

    def __init__(self, sender):
        self.sender = sender


class _RPCShim:
    "Adapter exposing the subset of BaseCmdMsg used by moat.lib.rpc.auth."

    def __init__(self, hello: Hello, sender, auth_data: dict[str, Any]):
        self.hello = hello
        self._sender = sender
        self.auth = attrdict(auth_data)
        self.is_server = (
            hello.rpc_auth_server if hello.rpc_auth_server is not None else hello.me_server
        )

    @property
    def auth_name(self):
        "Name presented to the RPC auth helper."
        return self.hello.me

    async def wait_ready(self, wait: bool = True):
        "The live RPC stream is already running."
        wait  # noqa:B018
        return False

    async def handle(self, msg, rcmd, _auth: bool = False):
        "Forward auth helper traffic to the already-open RPC sender."
        _auth  # noqa:B018
        return await self._sender.handle(msg, rcmd)

    def auth_data_out(self) -> dict:
        "Delegate extra auth-request data handling to Hello."
        return self.hello.auth_data_out()

    def auth_data_in(self, args, data: dict) -> None:
        "Delegate extra incoming auth-request data handling to Hello."
        self.hello.auth_data_in(args, data)

    def auth_data_res_out(self, role: str) -> dict:
        "Delegate extra auth-response data handling to Hello."
        return self.hello.auth_data_res_out(role)

    def auth_data_res_in(self, role: str, data: dict) -> None:
        "Delegate extra incoming auth-response data handling to Hello."
        self.hello.auth_data_res_in(role, data)

    def auth_skip(self) -> None:
        "Signal that the peer does not support RPC auth."
        self.hello.auth_skip()


@define
class Hello(CmdCommon):
    """
    This object handles the initial handshake between two MoaT links.

    Usage:

    * The ``handle`` method that you supplied to your `MsgHandler` must
      forward all incoming commands to `Hello.handler` while
      ``auth_data`' is `None`.

    * Call `Hello.run`.

    Note that due to the async nature of the protocol, additional commands
    may arrive even before `Hello.run` has returned.

    Negotiated auth data are in ``.auth_data``.
    """

    me: str | None = field(default=None)
    them: str | None = field(default=None)

    auth_data: Any = field(init=False, default=None)

    auth_in: dict[str, AuthMethod] = field(kw_only=True, default={}, converter=_to_dict)  # noqa:RUF008
    auth_out: dict[str, AuthMethod] = field(kw_only=True, default={}, converter=_to_dict)  # noqa:RUF008
    rpc_auth_modes: tuple[str, ...] | None = field(kw_only=True, default=None)
    rpc_auth_data: dict[str, Any] = field(kw_only=True, factory=dict)
    rpc_auth_server: bool | None = field(kw_only=True, default=None)

    me_server: bool = field(default=False)
    they_server: bool = field(init=False, default=False)

    _sync: anyio.Event = field(init=False, factory=anyio.Event)
    _done: anyio.Event = field(init=False, factory=anyio.Event)

    # min and max protocol versions we might accept
    protocol_min: int = field(kw_only=True, default=proto_version_min)
    protocol_max: int = field(kw_only=True, default=proto_version)

    # negotiated protocol version
    protocol_version: int = field(init=False, default=0)
    _rpc_auth: Any = field(init=False, default=None)
    _rpc_in: Any = field(init=False, default=None)
    _rpc_fallback: bool = field(init=False, default=False)
    _name_reply: str | None = field(init=False, default=None)
    _res_data: dict[str, Any] | None = field(init=False, default=None)

    def __attrs_post_init__(self):
        if self.me_server and self.me is None:
            raise ValueError("A server must have a name")

    def auth_data_out(self) -> dict:
        """
        Extra auth-request metadata shared between RPC auth and legacy Hello.
        """
        return {"moat.link": {"version": proto_version, "rname": self.them}}

    def auth_data_in(self, args, data: dict) -> None:
        """
        Process incoming auth-request metadata.

        Args:
            args: auth/hello positional arguments, with the peer name at index 2.
            data: auth/hello keyword metadata.
        """
        info = data.get("moat.link", {})
        if info is None:
            info = {}
        try:
            prot = info.get("version", args[0])
        except IndexError:
            prot = info.get("version", None)
        if prot is not None:
            if prot < self.protocol_min:
                raise ValueError("Protocol mismatch", prot)
            self.protocol_version = min(prot, self.protocol_max)

        try:
            self.they_server = args[1]
        except IndexError:
            pass

        local_name = info.get("rname", None)
        remote_name = args[2] if len(args) > 2 else None
        if remote_name is None:
            if self.them is None:
                logger.error("No remote name")
            else:
                self._name_reply = self.them
        elif self.them is None:
            self.them = remote_name
        elif self.them != remote_name:
            logger.debug("Remote name: %r / %r", remote_name, self.them)
            self._name_reply = self.them
            self.them = remote_name

        if local_name is None:
            return
        if self.me is None:
            self.me = local_name
        elif self.me != local_name:
            logger.debug("My name: %r / %r", local_name, self.me)

    def auth_data_res_out(self, role: str | None = None) -> dict:
        """
        Extra auth-response metadata shared between RPC auth and legacy Hello.
        """
        role  # noqa:B018
        if self._name_reply is None:
            return {}
        return {"name": self._name_reply}

    def auth_data_res_in(self, role: str | None, data: dict) -> None:
        """
        Process incoming auth-response metadata.
        """
        role  # noqa:B018
        data = dict(data)
        if (name := data.pop("name", None)) is not None:
            self.me = name
        self._res_data = data or None

    def auth_skip(self) -> None:
        """
        RPC auth isn't supported by the peer; caller may fall back to Hello/auth.
        """
        raise _NoRPCAuth

    def _rpc_modes(self) -> tuple[str, ...]:
        """
        RPC auth methods to try before the legacy hello/auth handshake.
        """
        if self.rpc_auth_modes is None:
            return ()
        return tuple(self.rpc_auth_modes)

    async def _run_rpc(self, sender: MsgSender):
        """
        Try the RPC auth protocol and return Hello-compatible result data.
        """
        modes = self._rpc_modes()
        if not modes:
            raise _NoRPCAuth

        from moat.lib.rpc.auth._base import Auth, AuthCmdIn, AuthDenied  # noqa: PLC0415

        cfg = attrdict(modes=[attrdict(mode=m) for m in modes])
        shim = _RPCShim(self, sender, self.rpc_auth_data)
        auth = Auth(cfg, shim)
        auth.base_root = _RPCRoot(sender)
        a_in = AuthCmdIn(auth)
        self._rpc_auth = auth
        self._rpc_in = a_in
        self._rpc_fallback = False
        self._name_reply = None
        self._res_data = None
        try:
            async with a_in:
                await a_in.task()
            if self._rpc_fallback:
                self._done = anyio.Event()
                raise _NoRPCAuth
            if isinstance(auth.ok, Exception):
                raise auth.ok
            self.auth_data = getattr(auth.ok, "name", True)
            if a_in.p_version is not None:
                self.protocol_version = min(a_in.p_version, self.protocol_max)
            self._done.set()
            return self._res_data or True
        except AuthDenied:
            self.auth_data = False
            self._done.set()
            raise
        except _NoRPCAuth:
            self._done = anyio.Event()
            raise
        except BaseException:
            if self._rpc_fallback:
                self._done = anyio.Event()
                raise _NoRPCAuth from None
            self.auth_data = False
            self._done.set()
            raise
        finally:
            self._rpc_in = None
            self._rpc_auth = None

    async def handle(self, msg: Msg, rcmd: list[PathElem], *prefix: Key) -> None:
        """
        Dispatch an incoming "hello" message
        """
        if prefix:
            raise NotImplementedError
        if self._rpc_in is not None and rcmd and rcmd[-1] is None:
            return await self._rpc_in.handle(msg, rcmd)
        if self._rpc_in is not None and len(rcmd) == 2 and rcmd[-1] == "i" and rcmd[0] == "hello":
            # The peer is using the legacy startup protocol. Let the incoming
            # hello proceed immediately, then fall back once our pending RPC
            # auth attempt receives its rejection.
            self._rpc_fallback = True
            self._sync.set()
        scmd = rcmd.pop()
        if scmd != "i":
            raise KeyError(scmd)
        if len(rcmd) == 1 and rcmd[0] == "hello":
            res = await self.do_hello(msg)
            await msg.result(res)
            return
        if len(rcmd) != 2 or rcmd[1] != "auth":
            raise ValueError("No Hello/Auth")

        if self.auth_data is not None:
            # Some other method already succeeded
            await msg.result(False)
            return
        a = self.auth_in.get(rcmd[0], None)
        if a is None:
            await msg.result(False)
        else:
            await a.handle(self, msg)

    def authorized(self, data: Any) -> bool:
        """
        Called by an auth method to indicate that authorization worked.

        Returns True if this method was the first to succeed.
        """
        if self.auth_data is not None:
            return False
        self.auth_data = data
        return True

    doc_i_hello = dict(
        _d="Process remote Hello msg",
        _r="auth state",
        _0="int:protocol",
        _1="bool:server flag",
        _2="str:sender's name",
        _3="str:recipient's name (temp by sender)",
        _4=["str:auth method"],
        _k="str:auth names",
        _kw="Any:auth params",
    )

    async def do_hello(self, msg) -> bool | None:
        """
        Process the remote hello message.

        Returns True if no auth is required.
        """
        try:
            res = await self._do_hello(msg)
        except BaseException:
            self.auth_data = False
            raise
        else:
            if self.auth_data is None:
                self.auth_data = res
            await msg.result(res)
        finally:
            self._done.set()

    async def _do_hello(self, msg) -> bool | dict:
        logger.debug("H IN %r %r", msg.args, msg.kw)
        it = iter(msg.args)
        auth = True
        remote_name = None
        local_name = None

        try:
            prot = next(it)

            # TODO special auth for servers?
            they_server = next(it)
            self.they_server = they_server
            if not self.they_server and not self.me_server:
                raise RuntimeError("Two clients cannot talk")

            remote_name = next(it)
            self._name_reply = None
            try:
                local_name = next(it)
            except StopIteration:
                self.auth_data_in(
                    (prot, they_server, remote_name),
                    {"moat.link": {"version": prot}},
                )
                raise
            else:
                self.auth_data_in(
                    (prot, they_server, remote_name),
                    {"moat.link": {"rname": local_name, "version": prot}},
                )
            if remote_name is None and self.them is None:
                auth = False
                raise StopIteration

            auth = next(it)

            if not next(it):
                raise RuntimeError("Not talking to a server")

        except StopIteration:
            pass

        # wait for the outgoing part to start
        await self._sync.wait()

        if auth is False:
            raise NotAuthorized("Remote blocks us", self.them)
        if auth is True:
            self.auth_data = True
            aux_data = self.auth_data_res_out(None)
            return aux_data or True

        if isinstance(auth, str):
            auth = (auth,)

        # Check for auth data in the Hello
        aux_data = {}
        for a in self.auth_in.values():
            res = await a.hello_in(self, msg.kw.get(a.name, None))
            if res is False:
                return False
            if res:
                if self.auth_data is None:
                    self.auth_data = True
                aux_data.update(self.auth_data_res_out(a.name))
                break

        # cycle through the remote side's accepted auth methods
        for a in auth:
            am = self.auth_out.get(a, None)
            if am is None:
                continue
            res = await am.chat(self, msg.kw.get(a, None))
            if res is None:
                continue
            aux_data = self.auth_data_res_out(am.name)
            if isinstance(res, dict):
                aux_data.update(res)
            if res is False or not aux_data:
                return res
            return aux_data

        # Nothing matched.
        return False

    async def run(self, sender: MsgSender, **kw):
        """
        Send our Hello message.
        """
        try:
            return await self._run_rpc(sender)
        except _NoRPCAuth:
            pass

        auths = []
        for a in self.auth_in.values():
            auths.append(a.name)
            if a.name not in kw:
                v = await a.hello_out()
                if v is not None:
                    kw[a.name] = v
        kw.update(self.auth_data_out())

        if len(auths) == 0:
            auths = True
        elif len(auths) == 1:
            auths = auths[0]

        logger.debug("H OUT %d %s %s %r %r", proto_version, self.me, self.them, auths, kw)
        self._sync.set()
        res = await sender.cmd(
            P("i.hello"),
            proto_version,
            self.me_server,
            self.me,
            self.them,
            auths,
            **kw,
        )
        res = res.kw or res[0]

        if res is False:
            raise NotAuthorized("Server %r rejects us", self.them)
        if isinstance(res, dict):
            self.auth_data_res_in(None, res)

        # Wait for the incoming side of the auth/hello dance to succeed
        await self._done.wait()
        return res

    async def wait_done(self):
        "wait until done"
        await self._done.wait()
