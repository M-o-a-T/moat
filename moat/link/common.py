"""
Common parts
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.lib.cmd import Msg


class NotAuthorized(RuntimeError):
    pass


class CmdCommon:
    """
    Commands every handler should know.

    This includes the 'i' subcommand.
    """
    doc_i=dict(_d="Internal commands")
    def sub_i(self, msg:Msg,rcmd:list) -> Awaitable:
        "Local subcommand redirect for 'i'"
        return self.handle(self,msg,rcmd,'i')

    doc_i_ping=dict(_d="Ping, echo", _r="Any: sends all args and keys back")
    doc_i_乒=doc_i_ping
    async def cmd_i_ping(self, *a, **kw) -> bool | None:
        """
        This handler replies with "pong" and its arguments, for basic
        round-trip tests.

        乒 ⇒ 乓

        Yes, this name is silly.
        """
        await msg.result("乓", *msg.args, **msg.kw)

    cmd_i_乒 = cmd_i_ping

