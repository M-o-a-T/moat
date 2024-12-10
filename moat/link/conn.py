"""
Bare-bones connection to a MoaT server
"""
from __future__ import annotations


from attrs import define,field
from moat.util import CtxObj
from moat.lib.cmd import CmdHandler
from moat.lib.cmd.anyio import run as run_stream
from . import protocol_version

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.lib.cmd import MsgIn
    from typing import Awaitable

@define
class Conn(CtxObj):
    """
    Connection to a MoaT server.

    This encapsulates a bare-bones link to a server, plus the initial
    handshake and auth support.
    """

    me:str
    them:str
    host:str
    port:int
    token:str|None = field(kw_only=True, default=None)
    auth:bool|None|str|list[str] = field(init=False, default=None)

    _callback: MsgIn = field(kw_only=True, default=None)
    _conn: CmdHandler = field(init=False)

    def __attrs_post_init__(self):
        self._conn = CmdHandler(self._callback)

    async def _ctx(self):
        async with (
                await anyio.connect_tcp((self.host,self.port)) as conn,
                run_stream(self._conn, conn),
            ):
            await self._hello()
            yield self


    async def _hello(self):
        """
        Send hello message, sets ``.name`` and ``.auth``.

        Returns True if no auth is required.
        """
        res = await self.cmd(P("i.hello"), protocol_version, self.me, self.them, self.token)
        it = iter(res)
        self.link_protocol = protocol_version
        self._server_name = srv.meta.origin
        auth = True

        try:
            prot = next(it)
            if prot is False:
                raise ValueError("Protocol mismatch")
            elif prot is None:
                pass
            else:
                self.link_protocol = min(tuple(prot), protocol_version)

            server_name = next(it)
            if server_name is None:
                pass
            elif server_name != self.them:
                self.logger.warning("Server name: %r / %r", server_name, srv.meta.origin)

            name = next(it)
            if name is not None:
                if self.name:
                    self.logger.warning("Client name: %r / %r", name, self.name)
                self.name = name

            if not next(it):
                raise RuntimeError("Not talking to a server")

            auth = next(it)
        except StopIteration:
            pass

        self.auth = auth
        if auth is False:
            raise RuntimeError("Server %r didn't like us (%s:%d)", self.them, self.host,self.port)
        return auth is True


    def cmd(self, *a, **kw) -> Awaitable:
        "Forwarded to the link"
        return self._conn.cmd(*a, **kw)

    def stream_r(self, *a, **kw) -> Awaitable:
        "Forwarded to the link"
        return self._conn.stream_r(*a, **kw)

    def stream_w(self, *a, **kw) -> Awaitable:
        "Forwarded to the link"
        return self._conn.stream_w(*a, **kw)

    def stream_rw(self, *a, **kw) -> Awaitable:
        "Forwarded to the link"
        return self._conn.stream_rw(*a, **kw)
