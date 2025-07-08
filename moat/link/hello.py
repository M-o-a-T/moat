"""
Bare-bones connection to a MoaT server
"""

from __future__ import annotations


from attrs import define, field
from moat.util import P
import anyio
from moat.lib.cmd.base import MsgHandler, MsgSender
from . import protocol_version as proto_version, protocol_version_min as proto_version_min
from .common import CmdCommon
from .auth import AuthMethod
import logging

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any
    from collections.abc import Awaitable
    from moat.lib.cmd.base import MsgHandler
    from moat.lib.cmd.msg import Msg
    from moat.lib.cmd import Key

logger = logging.getLogger(__name__)


class NotAuthorized(RuntimeError):
    pass


def _to_dict(x: list[AuthMethod]) -> dict[str, AuthMethod]:
    return {a.name: a for a in x}


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

    auth_in: dict[str, AuthMethod] = field(kw_only=True, default={}, converter=_to_dict)
    auth_out: dict[str, AuthMethod] = field(kw_only=True, default={}, converter=_to_dict)

    me_server: bool = field(default=False)
    they_server: bool = field(init=False, default=False)

    _sync: anyio.Event = field(init=False, factory=anyio.Event)
    _done: anyio.Event = field(init=False, factory=anyio.Event)

    # min and max protocol versions we might accept
    protocol_min: int = field(kw_only=True, default=proto_version_min)
    protocol_max: int = field(kw_only=True, default=proto_version)

    # negotiated protocol version
    protocol_version: int = field(init=False, default=0)
    hello_seen: anyio.Event = field(init=False, factory=anyio.Event)
    hello_a: tuple[Any, ...] = field(init=False, default=())
    hello_kw: dict[str, Any] = field(init=False, default={})

    def __init__(self, *a, **kw):
        super().__init__()
        self.__attrs_init__(*a, **kw)  # pyright:ignore
        if self.me_server and self.me is None:
            raise ValueError("A server must have a name")

    async def handle(self, msg: Msg, rcmd: list[Key], *prefix:Key) -> None:
        """
        Dispatch an incoming "hello" message
        """
        if prefix:
            raise NotImplementedError
        if rcmd.pop() != "i":
            raise ValueError("No Hello/Auth")
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
        aux_data = {}

        try:
            prot = next(it)
            if prot < self.protocol_min:
                raise ValueError("Protocol mismatch", prot)
            self.protocol_version = min(prot, self.protocol_max)

            # TODO special auth for servers?
            self.they_server = next(it)
            if not self.they_server and not self.me_server:
                raise RuntimeError("Two clients cannot talk")

            # Remote names
            # If the remote is nameless, use ours.
            # If the remote is a server, keep its name.
            # If the name are the same, no problem.
            # If the remote name starts with an underscore, tell it to use ours.
            # If the remote name starts with a bang, strip it.
            # Otherwise prefix with our name.
            remote_name = next(it)
            if remote_name is None:
                if self.them is None:
                    logger.error("No remote name")
                    auth=False
                    raise StopIteration
                aux_data["name"] = self.them
            elif self.them is None:
                self.them = remote_name
            elif self.them != remote_name:
                if remote_name.startswith("_"):
                    logger.debug("Remote name: %r / %r", remote_name, self.them)
                    aux_data["name"] = self.them
                elif self.they_server:
                    self.them = remote_name
                elif remote_name[0] == "!":
                    self.them = remote_name[1:]
                else:  # we're the server, so use our name as a prefix
                    self.them = f"{self.me}.{remote_name}"
                    logger.debug("Remote name: %r", self.them)
                    aux_data["name"] = self.them

            local_name = next(it)
            if local_name is None:
                pass
            elif self.me is None:
                self.me = local_name
            elif self.me != local_name:
                logger.debug("My name: %r / %r", local_name, self.me)
                if not self.me_server:
                    self.me = local_name

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
            return aux_data or True

        if isinstance(auth, str):
            auth = (auth,)

        # Check for auth data in the Hello
        for a in self.auth_in.values():
            res = await a.hello_in(self, msg.kw.get(a.name, None))
            if res is False:
                return False
            if res:
                if self.auth_data is None:
                    self.auth_data = True
                break

        # cycle through the remote side's accepted auth methods
        for a in auth:
            am = self.auth_out.get(a, None)
            if am is None:
                continue
            res = await am.chat(self, self.hello_kw.get(a, None))
            if res is None:
                continue
            if isinstance(res,dict):
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

        auths = []
        for a in self.auth_in.values():
            auths.append(a.name)
            if a.name not in kw:
                v = await a.hello_out()
                if v is not None:
                    kw[a.name] = v

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

        # Wait for the incoming side of the auth/hello dance to succeed
        await self._done.wait()
        return res
