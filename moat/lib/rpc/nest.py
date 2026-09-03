"""
# MsgHandler on top of a message stream

MoaT-Cmd offers no way to discover who your caller is. This is sometimes
inconvenient.

As a real-world example, assume you have an embedded device that's
connected to some environmental sensors and a ventilator, so it needs to
calculate the air quality. Assume further that the library to do this
is too large, or closed-source with binaries not available for its
architecture (hello, Bosch, please reconsider), or single-theaded but the
embedded device doesn't have threads.

So you use MoaT-Cmd to call out to your server, which has the library. The
library then wants to access your embedded device's i²c bus to actually
read the data, but it doesn't have its address.

The solution is to multiplex the stream to the server … with error handling,
streaming the resulting measurements, and all that. But why re-invent the
wheel, when MoaT-Cmd already *is* a multiplexing library, and you're using
it anyway?

Hence this stream handler.

See ``tests/moat_lib_rpc/test_nest.py`` for an example.

"""

from __future__ import annotations

import anyio
import sys

from moat.lib.micro import ACM, AC_exit, log

from .base import MsgHandler
from .stream import HandlerStream

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from moat.util import attrdict
    from moat.lib.path import PathElem
    from moat.lib.rpc import Msg

    from .base import BaseMsgHandler

__all__ = ["CmdStream", "rpc_on_rpc"]


class CmdStream(HandlerStream):
    """
    This command stream uses the data from a single message as its
    transport.

    Args:
        cmd: the command handler to call for incoming commands.
             May be ``None`` if you don't handle any.
        msg: the stream to use. **It must be wrapped in an `async with
             msg.stream()` block.**
        debug: Prefix for tracing. Note that the trace handles raw
               message data and does not decode transactions.
    """

    __msg: Msg
    auth: object | None = None

    def __init__(
        self,
        cmd: BaseMsgHandler | None,
        msg: Msg,
        debug: str | None = None,
        **kw,
    ):
        self.__msg = msg
        self.__debug = debug

        super().__init__(cmd, **kw)

    async def read_stream(self):  # noqa: D102
        msg = self.__msg

        async for m in msg:
            if m.kw:
                log("R%s: incoming keywords ignored!? %r", self.__debug or "", m)
            elif self.__debug:
                log("R%s %r", self.__debug, m)
            await self.msg_in(cast("list", m.args_l))

    async def write_stream(self):  # noqa: D102
        msg = self.__msg
        while True:
            try:
                m = await self.msg_out()
            except EOFError:
                return
            if self.__debug:
                log("W%s %r", self.__debug, m)

            await msg.send(*m)


class _AuthAdapter:
    """Minimal adapter so :class:`~moat.lib.rpc.Auth` can drive a CmdStream.

    Implements the interface that ``Auth.process()`` expects from its
    ``parent``: :meth:`handle`, :meth:`check_rdy`,
    :meth:`auth_data_out` / friends, :meth:`auth_skip`, and
    :meth:`wait_ready`.
    """

    def __init__(
        self,
        cfg: attrdict,
        msg: Msg,
        cmd: BaseMsgHandler | None,
        *,
        is_server: bool = False,
    ):
        from moat.lib.rpc import Auth  # noqa: PLC0415

        self.cfg = cfg
        self.msg = msg
        self.cmd = cmd
        self.is_server = is_server
        self.auth_name: str | None = None

        self.auth = None
        if "auth" in cfg:
            from moat.util import attrdict as ad  # noqa: PLC0415

            self.auth = ad()
            if "pytest" in sys.modules:
                tcfg = cfg.auth.get("test", None)
                if tcfg is not None:
                    self.auth.update(tcfg)

        self._auth = Auth(cfg.auth, self)  # ty:ignore[invalid-argument-type]
        self._stream: CmdStream | None = None
        self._tg: object | None = None
        self._auth_result: object | None = None

    @property
    def stream(self) -> CmdStream:
        "The CmdStream, available after auth setup."
        s = self._stream
        assert s is not None
        return s

    @property
    def auth_result(self) -> object | None:
        """The auth result (a SubAuth instance) after auth completes."""
        return self._auth_result

    async def run(self, AC) -> CmdStream:
        """Run auth over the CmdStream; return after auth completes.

        The auth handshake (:class:`AuthCmdIn`) runs in the CmdStream's
        own task group, so it stays alive for the lifetime of the stream.
        After auth, the CmdStream handler is swapped to the user's handler.
        """
        from moat.lib.rpc import MsgSender  # noqa: PLC0415
        from moat.lib.rpc.auth._base import AuthCmdIn  # noqa: PLC0415

        if self.cmd is not None:
            root = MsgSender(self.cmd)  # ty:ignore[invalid-argument-type]
        else:
            root = MsgSender(_NullHandler())

        # Create the AuthCmdIn that will handle auth negotiations.
        self._auth.base_root = root
        a_in = AuthCmdIn(self._auth)

        # Set up the CmdStream with a_in as the handler.
        stream = await AC(CmdStream(a_in, self.msg))
        self._stream = stream

        # Start the auth handshake in the CmdStream's task group.
        async def run_auth():
            async with a_in:
                await a_in.task()
                await anyio.sleep_forever()

        stream.start(run_auth)

        # Wait for auth to complete.
        await self._auth.wait_done()
        ok = self._auth.ok
        if isinstance(ok, Exception):
            raise ok
        self._auth_result = ok

        # Swap the CmdStream handler to the user's handler.
        # Post-auth commands now go directly to the user.
        stream._sender = self.cmd  # noqa: SLF001
        return stream

    async def stop(self) -> None:
        """Shut down the CmdStream."""
        if self._stream is not None:
            await self._stream.__aexit__(None, None, None)
            self._stream = None

    async def check_rdy(self, msg: Msg, rcmd: list[PathElem]) -> None:
        "Auth helper hook."
        msg  # noqa: B018
        rcmd  # noqa: B018

    def auth_data_out(self) -> dict:
        "Auth helper hook."
        return {}

    def auth_data_in(self, args, data) -> None:
        "Auth helper hook."
        args  # noqa: B018
        data  # noqa: B018

    def auth_data_res_out(self, role: str) -> dict:
        "Auth helper hook."
        role  # noqa: B018
        return {}

    def auth_data_res_in(self, role: str, data) -> None:
        "Auth helper hook."
        role  # noqa: B018
        data  # noqa: B018

    def auth_skip(self) -> None:
        "Accept missing remote auth."
        pass

    async def wait_ready(self, wait: bool = True) -> bool | None:  # noqa: ARG002
        "Wait for the CmdStream to be ready."
        if self._stream is None:
            return None
        return False

    async def handle(self, msg: Msg, rcmd: list[PathElem], _auth: bool = False):
        """Forward a message through the CmdStream (or auth handler)."""
        if not _auth:
            return await self._auth.handle(msg, rcmd)
        s = self._stream
        if s is None:
            raise RuntimeError("CmdStream not set up")
        return await s.handle(msg, rcmd)


class _NullHandler(MsgHandler):
    "Trivial handler that accepts and discards everything."

    pass


class rpc_on_rpc:
    """
    Run a command handler on top of a message stream @msg.
    """

    def __init__(
        self,
        cmd: BaseMsgHandler,
        msg: Msg,
        *,
        auth: attrdict | None = None,
        is_server: bool = False,
        debug: bool = False,
        logger=None,
    ):
        """
        Args:
            cmd: handler for incoming messages. May be `None`.
            msg: MoaT-RPC Transport stream
            auth: Optional auth configuration.  When set, auth negotiation
                  runs over the stream before yielding; ``cmdo.auth`` will
                  contain the result data.
            is_server: When ``auth`` is set, declare this side as the server
                       (listener) or client (connector).  Defaults to client.
            debug: flag whether to emit a message debug trace
            logger: callable for debugging internal state

        This is an async context manager that yields a `CmdStream`.
        """
        self.cmd = cmd
        self.msg = msg
        self.auth = auth
        self.is_server = is_server
        self.debug = debug
        self.logger = logger
        self._adapter: _AuthAdapter | None = None

    async def __aenter__(self) -> CmdStream:
        AC = ACM(self)
        try:
            if self.auth is not None:
                # Auth mode: the adapter creates the CmdStream with AuthCmdIn
                # as its handler, runs auth over it, then swaps the handler
                # to the user's cmd.
                self._adapter = _AuthAdapter(
                    self.auth, self.msg, self.cmd, is_server=self.is_server
                )
                await self._adapter.run(AC)
                stream = self._adapter.stream
                if stream is None:
                    raise RuntimeError("Auth adapter did not create a stream")
                stream.auth = self._adapter.auth_result
            else:
                dbg = "" if self.debug else None
                stream = await AC(CmdStream(self.cmd, self.msg, debug=dbg, logger=self.logger))

            return stream

        except BaseException:
            if self._adapter is not None:
                await self._adapter.stop()
                self._adapter = None
            raise

    async def __aexit__(self, *exc):
        if self._adapter is not None:
            self._adapter = None  # CmdStream cleanup handled by AC_exit
        return await AC_exit(self, *exc)
