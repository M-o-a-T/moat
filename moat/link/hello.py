"""
Bare-bones connection to a MoaT server
"""

from __future__ import annotations


from attrs import define, field
from moat.util import P
import anyio
from moat.lib.cmd.base import MsgHandler
from . import protocol_version, protocol_version_min
from .common import CmdCommon
import logging

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.lib.cmd import CmdHandler
    from collections.abc import Awaitable

logger = logging.getLogger(__name__)


class NotAuthorized(RuntimeError):
    pass


def _to_dict(x: list[AuthMethod]) -> dict[str, AuthMethod]:
    return {a.name: a for a in x}


@define
class Hello(CmdCommon, MsgHandler):
    """
    This object handles the initial handshake between two MoaT links.

    Usage:

    * The ``handle`` method that you supplied to your `CmdHandler` must
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

    _sync: anyio.Event | None = field(init=False, factory=anyio.Event)
    _done: anyio.Event | None = field(init=False, factory=anyio.Event)

    # min and max protocol versions we might accept
    protocol_min: int = field(kw_only=True, default=protocol_version_min)
    protocol_max: int = field(kw_only=True, default=protocol_version)

    # negotiated protocol version
    protocol_version: int = field(init=False, default=0)
    hello_seen: anyio.Event = field(init=False, factory=anyio.Event)
    hello_a: tuple[Any] = field(init=False, default=())
    hello_kw: dict[str, Any] = field(init=False, default={})

    def __init__(self, *a, **kw):
        super().__init__()
        self.__attrs_init__(*a, **kw)

    async def handle(self, msg: Msg, rpath: list[str]) -> bool | None:
        """
        Dispatch an incoming "hello" message
        """
        if rpath.pop() != "i":
            raise ValueError("No Hello/Auth")
        if len(rpath) == 1 and rpath[0] == "hello":
            return await self.cmd_i_hello(msg)
        if len(rpath) != 2 or rpath[1] != "auth":
            raise ValueError("No Hello/Auth")

        if self.data is not None:
            # Some other method already succeeded
            return False
        a = self.auth_in.get(msg.cmd[0], None)
        if a is None:
            return False
        return await a.handle(self, msg)

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
        _1="str:remote name",
        _2="str:local name",
        _3="bool:server flag",
        _4=["str:auth method"],
    )

    async def cmd_i_hello(self, msg) -> bool | None:
        """
        Process the remote hello message.

        Returns True if no auth is required.
        """
        try:
            res = await self._cmd_i_hello(msg)
        except BaseException:
            self.auth_data = False
            raise
        else:
            if self.auth_data is None:
                self.auth_data = res
            return res
        finally:
            self._done.set()

    async def _cmd_i_hello(self, msg) -> bool | None:
        logger.info("H IN %r %r", msg.args, msg.kw)
        it = iter(msg.args)
        auth = True

        try:
            prot = next(it)
            if prot < self.protocol_min:
                raise ValueError("Protocol mismatch", prot)
            self.protocol_version = min(prot, self.protocol_max)

            me_server = next(it)
            if not me_server and not self.me_server:
                raise RuntimeError("Two clients cannot talk")

            remote_name = next(it)
            if remote_name is None:
                pass
            elif self.them is None:
                self.them = remote_name
            elif self.them != remote_name:
                logger.warning("Remote name: %r / %r", remote_name, self.them)

            local_name = next(it)
            if local_name is None:
                pass
            elif self.me is None:
                self.me = local_name
            elif self.me != local_name:
                logger.warning("My name: %r / %r", local_name, self.me)
                if not self.me_server:
                    self.me = local_name

            auth = next(it)

            if not next(it):
                raise RuntimeError("Not talking to a server")

        except StopIteration:
            pass

        await self._sync.wait()

        if auth is False:
            raise NotAuthorized("Server %r blocks us (%s:%d)", self.them, self.host, self.port)
        if auth is True:
            self.auth_data = True
            return True

        if isinstance(auth, str):
            auth = (auth,)

        # Check for auth data in the Hello
        for a in self.auth_in:
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
            if res is not None:
                return res

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

        logger.info("H OUT %d %s %s %r %r", protocol_version, self.me, self.them, auths, kw)
        self._sync.set()
        (res,) = await sender.cmd(
            P("i.hello"),
            protocol_version,
            self.me_server,
            self.me,
            self.them,
            auths,
            **kw,
        )

        if res is False:
            raise NotAuthorized("Server %r rejects us (%s:%d)", self.them, self.host, self.port)

        # Wait for the incoming side of the auth/hello dance to succeed
        await self._done.wait()
