"""
Bare-bones connection to a MoaT server
"""

from __future__ import annotations

import anyio
import logging

from attrs import define, field

from moat.util import attrdict
from moat.lib.rpc import Auth, AuthCmdIn, AuthDenied

from . import protocol_version as proto_version
from . import protocol_version_min as proto_version_min
from .common import CmdCommon

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from moat.lib.path import PathElem
    from moat.lib.rpc import Msg, MsgSender

    from typing import Any

logger = logging.getLogger(__name__)


class NotAuthorized(RuntimeError):  # noqa: D101
    pass


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

    if TYPE_CHECKING:

        def __init__(
            self,
            me: str | None = None,
            them: str | None = None,
            *,
            rpc_auth_modes: tuple[str, ...] | None = None,
            rpc_auth_data: dict[str, Any] = ...,
            rpc_auth_server: bool | None = None,
            me_server: bool = False,
            protocol_min: int = proto_version_min,
            protocol_max: int = proto_version,
        ) -> None: ...

    me: str | None = field(default=None)
    them: str | None = field(default=None)

    auth_data: Any = field(init=False, default=None)

    rpc_auth_modes: tuple[str, ...] | None = field(kw_only=True, default=None)
    rpc_auth_data: dict[str, Any] = field(kw_only=True, factory=dict)
    rpc_auth_server: bool | None = field(kw_only=True, default=None)

    me_server: bool = field(default=False)
    they_server: bool = field(init=False, default=False)

    _done: anyio.Event = field(init=False, factory=anyio.Event)

    # min and max protocol versions we might accept
    protocol_min: int = field(kw_only=True, default=proto_version_min)
    protocol_max: int = field(kw_only=True, default=proto_version)

    # negotiated protocol version
    protocol_version: int = field(init=False, default=0)
    _rpc_auth: Any = field(init=False, default=None)
    _rpc_in: Any = field(init=False, default=None)
    _rpc_init: anyio.Event = field(init=False, factory=anyio.Event)
    _rpc_accepting: bool = field(init=False, default=False)
    _reply: dict[str, Any] = field(init=False, factory=dict)
    _res_data: dict[str, Any] | None = field(init=False, default=None)

    def __attrs_post_init__(self):
        if self.me_server and self.me is None:
            raise ValueError("A server must have a name")

    def auth_data_out(self) -> dict:
        """
        Extra auth-request metadata shared between RPC auth and legacy Hello.
        """
        res = {"version": proto_version}
        if self.them:
            res["rname"] = self.them
        return {"moat.link": res}

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
                self._reply["name"] = self.them
        elif self.them is None:
            self.them = remote_name
        elif self.them != remote_name:
            logger.debug("Remote name: %r / %r", remote_name, self.them)
            self._reply["name"] = self.them
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
        if role is not None and self._rpc_in is not None:
            # We are about to send a successful incoming RPC-auth reply.
            # At this point non-auth commands may pass through.
            self._rpc_accepting = True
        return self._reply

    @staticmethod
    def is_auth_cmd(rcmd: list[PathElem]) -> bool:
        """
        Check whether this command belongs to startup authentication.
        """
        if not rcmd:
            return False
        if rcmd[-1] is None:
            return True
        return False

    @property
    def auth_accepting(self) -> bool:
        """
        Non-auth commands may pass while RPC auth cleanup is still running.
        """
        return self._rpc_accepting

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
        RPC auth isn't supported by the peer.
        """
        raise NotAuthorized("Peer does not support RPC auth")

    def _rpc_modes(self) -> tuple[str, ...]:
        """
        RPC auth methods to try before the legacy hello/auth handshake.
        """
        if self.rpc_auth_modes is None:
            return ()
        return tuple(self.rpc_auth_modes)

    async def run(self, sender: MsgSender):
        """
        Run the RPC auth protocol.
        """
        modes = self._rpc_modes()
        if not modes:
            self._rpc_init.set()
            self._done.set()
            raise NotAuthorized("No auth modes configured")

        cfg = attrdict(modes=[attrdict(mode=m) for m in modes])
        shim = _RPCShim(self, sender, self.rpc_auth_data)
        auth = Auth(cfg, cast("Any", shim))
        auth.base_root = cast("MsgSender", _RPCRoot(sender))
        self._rpc_auth = auth
        a_in = AuthCmdIn(auth)
        self._rpc_in = a_in
        self._rpc_init.set()
        self._rpc_accepting = False
        self._reply = {}
        self._res_data = None
        try:
            async with a_in:
                await a_in.task()
            if isinstance(auth.ok, Exception):
                raise auth.ok
            self.auth_data = getattr(auth.ok, "name", True)
            if a_in.p_version is not None:
                self.protocol_version = min(a_in.p_version, self.protocol_max)
            return self._res_data or True
        except BaseException:
            self.auth_data = False
            raise
        finally:
            self._done.set()
            self._rpc_in = None
            self._rpc_auth = None

    async def handle(self, msg: Msg, rcmd: list[PathElem]) -> None:
        """
        Dispatch an incoming auth message
        """
        if self.is_auth_cmd(rcmd) and rcmd[-1] is None:
            # RPC auth can arrive before ``run`` had a chance to install ``_rpc_in``.
            if self._rpc_in is None:
                await self._rpc_init.wait()
            if self._rpc_in is None:
                raise AuthDenied(msg)
            return await self._rpc_in.handle(msg, rcmd)
        raise KeyError(rcmd)

    async def wait_done(self):
        "wait until done"
        await self._done.wait()
