"""RPC infrastructure for remote REPL access."""

from __future__ import annotations

import anyio
import inspect

from moat.lib.rpc import MsgHandler

TYPE_CHECKING = False

if TYPE_CHECKING:
    from moat.lib.rpc import Msg

    from .console import Console


class MsgConsole(MsgHandler):
    """
    RPC handler that wraps a Console instance and exposes its methods via cmd_* handlers.

    This allows remote access to console operations via the MsgSender interface.
    """

    def __init__(self, console: Console):
        self.console = console

        for k in dir(console):
            if k[0] == "_":
                continue
            try:
                v = getattr(console, k)
            except AttributeError:
                continue
            if inspect.iscoroutinefunction(v):
                setattr(self, f"cmd_{k}", v)

    async def stream_raw(self, msg: Msg):
        """
        RPC data stream for raw I/O.
        """
        async with msg.stream() as ms, anyio.create_task_group() as tg:
            try:
                await self.console.prepare(reader=False)

                @tg.start_soon
                async def sender():
                    while True:
                        data = await self.console.rd(32)
                        await ms.send(data)

                async for data in ms:
                    await self.console.wr(data)
            finally:
                with anyio.move_on_after(1, shield=True):
                    await self.console.restore()

    async def stream_evt(self, msg: Msg):
        """
        RPC data stream for events.
        """
        async with msg.stream() as ms, anyio.create_task_group() as tg:
            try:
                await self.console.prepare(reader=True)

                @tg.start_soon
                async def sender():
                    while True:
                        try:
                            data = await self.console.get_event()
                        except EOFError:  # from mock console
                            tg.cancel_scope.cancel()
                            break
                        await ms.send(data)

                async for data in ms:
                    await self.console.wr(data)
            finally:
                with anyio.move_on_after(1, shield=True):
                    await self.console.restore()
