from __future__ import annotations

from moat.link import protocol_version

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import ClassVar, ReadOnly, Any
    from moat.lib.cmd import MsgHandler, Msg, Key
    from .hello import Hello

__all__ = ["AuthMethod", "TokenAuth", "AnonAuth", "NoAuth"]


class AuthMethod:
    name: ClassVar[str]

    async def hello_out(self) -> Any|None:
        """
        Return data that should be included in the Hello message we
        send.

        The default is no data.
        """
        return None

    async def hello_in(self, conn: Hello, data: Any) -> bool | None:
        """
        This may implement "The remote side authorizes itself to me" based
        on data sent in the remote's Hello message.

        If this returns False, the auth call fails; if True, other auth
        methods are skipped.

        Uf the remote uses the current protocol level and there is data,
        this will fail. Otherwise, do nothing.
        """
        if data is None or conn.protocol_version < protocol_version:
            return None

        return False

    async def chat(self, conn: Hello, data: Any):
        """
        The recipient of a Hello message whose ``auth`` member includes our
        name calls this method. It's supposed to call ``conn.cmd(i.auth.NAME), …)``
        (or a streaming version thereof) and return its eventual result.

        This method implements "I authorize me to the remote side".

        The default is to do nothing.
        """
        return None

    async def handle(self, conn: Hello, msg: Msg) -> None:
        """
        The dispatcher calls this method with an incoming ``i.auth.NAME`` message.

        It thus implements "The remote side authorizes itself to me".

        The default is to fail, because the remote shouldn't call us without reason.
        """
        await msg.result(False)


class TokenAuth(AuthMethod):
    name: ClassVar[ReadOnly[str]] = "token"

    def __init__(self, *token: str):
        self._token = token

    async def hello_out(self):
        return self._token[0] if self._token else None

    async def hello_in(self, conn, data):
        """
        Check the incoming token.
        """
        # We don't actually chat here.
        # The remote should have sent the token in its Hello message.

        if data is None:
            # client didn't send data: try another method
            return None

        if data in self._token:
            # save the token that was actually used
            # returns False if some other auth method succeeded first
            return conn.authorized(data) or None

        # wrong token: kick them off
        return False

    async def handle(self, conn: MsgHandler, msg: Msg):
        """
        The client shouldn't send an `i.auth.token` message.
        """
        await msg.result(False)


class AnonAuth(AuthMethod):
    """
    Auth method of last resort: anonymous login.
    """

    name: ClassVar[ReadOnly[str]] = "anon"

    async def hello_out(self):
        return None

    async def chat(self, conn, data):
        conn.authorized(self)
        return True

    async def handle(self, conn: MsgHandler, msg: Msg):
        return True


class NoAuth(AuthMethod):
    """
    Reject auth attempts.
    """

    name: ClassVar[ReadOnly[str]] = "no"

    async def hello_out(self):
        return None

    async def chat(self, conn, data):
        "reject"
        return False

    async def handle(self, conn: MsgHandler, msg: Msg, *prefix:Key):
        "reject"
        return False
