"""RPC infrastructure for remote REPL access."""

from __future__ import annotations

import anyio
import inspect

from moat.lib.rpc import MsgHandler

TYPE_CHECKING = False

if TYPE_CHECKING:
    from moat.lib.rpc import Msg
    from moat.lib.stream import TermBuf

__all__ = ["MsgTerm"]


class MsgTerm(MsgHandler):
    """
    RPC handler that wraps a TermBuf instance and exposes its methods via cmd_* handlers.

    This allows remote access to terminal operations via the MsgSender interface.
    """

    def __init__(self, term: TermBuf):
        self.term = term

        for k in dir(term):
            if k[0] == "_":
                continue
            try:
                v = getattr(term, k)
            except AttributeError:
                continue
            if inspect.iscoroutinefunction(v):
                fn = f"cmd_{k}"
                if not hasattr(self, fn):
                    setattr(self, f"cmd_{k}", v)

    async def stream_raw(self, msg: Msg):
        """
        RPC data stream for raw I/O.
        """
        async with msg.stream() as ms, anyio.create_task_group() as tg:
            try:
                await self.term.set_raw()

                @tg.start_soon
                async def sender():
                    buf = bytearray(32)
                    while True:
                        try:
                            n = await self.term.rd(buf)
                            data = bytes(buf[:n])
                        except EOFError:
                            break
                        await ms.send(data)
                    tg.cancel_scope.cancel()

                async for data in ms:
                    await self.term.wr(data)  # type: ignore[arg-type]
                tg.cancel_scope.cancel()
            finally:
                with anyio.move_on_after(1, shield=True):
                    await self.term.set_orig()
