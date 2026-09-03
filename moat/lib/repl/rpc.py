"""RPC infrastructure for remote REPL access."""

from __future__ import annotations

import anyio

from moat.lib.rpc import MsgHandler

TYPE_CHECKING = False

if TYPE_CHECKING:
    from moat.lib.rpc import Msg
    from moat.lib.stream import TermBuf

__all__ = ["MsgTerm"]

#: Methods that should not be exposed as RPC commands despite being async.
_SKIP_METHODS = frozenset({"setup", "teardown", "stream"})


class MsgTerm(MsgHandler):
    """
    RPC handler that wraps a :class:`~moat.lib.stream.TermBuf` instance and
    exposes its terminal methods as ``cmd_*`` handlers.

    This allows remote access to terminal operations via the MsgSender
    interface.  Public async methods of the wrapped ``TermBuf`` (except
    lifecycle methods in :data:`_SKIP_METHODS`) are automatically forwarded.
    """

    def __init__(self, term: TermBuf):
        self.term = term

        import inspect  # noqa: PLC0415

        for name in dir(term):
            if name[0] == "_" or name in _SKIP_METHODS:
                continue
            try:
                meth = getattr(term, name)
            except AttributeError:
                continue
            if inspect.iscoroutinefunction(meth):
                fn = f"cmd_{name}"
                if not hasattr(self, fn):
                    setattr(self, fn, meth)

    async def stream_raw(self, msg: Msg):
        """RPC bidirectional data stream for raw terminal I/O.

        Switches the terminal to raw mode for the duration of the stream,
        forwarding keystrokes to the remote side and writing remote data
        back to the terminal.  The terminal is restored to its original
        state on exit.
        """
        async with msg.stream() as ms, anyio.create_task_group() as tg:
            try:
                await self.term.set_raw()

                @tg.start_soon
                async def _sender():
                    buf = bytearray(32)
                    while True:
                        try:
                            n = await self.term.rd(buf)
                        except EOFError:
                            break
                        await ms.send(bytes(buf[:n]))
                    tg.cancel_scope.cancel()

                async for data in ms:
                    await self.term.wr(data[0])
                tg.cancel_scope.cancel()
            finally:
                with anyio.move_on_after(1, shield=True):
                    await self.term.set_orig()
