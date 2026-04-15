"""
Command tree support for MoaT commands
"""

from __future__ import annotations

from moat.lib.micro import L

from .dir import BaseSubCmd
from .layer import BaseLayerCmd

# Typing

from typing import TYPE_CHECKING, cast  # isort:skip

if TYPE_CHECKING:
    from moat.lib.micro import _TaskGroupProto
    from moat.lib.rpc import BaseConnIter
    from moat.lib.stream import BaseBuf, BaseMsg

    from collections.abc import Callable


class BaseListenOneCmd(BaseLayerCmd):
    """
    An app that runs a listener and accepts a single connection.

    Override `listener` to return it.

    TODO: this needs to be a stream layer instead: we want the
    Reliable module to be able to pick up where it left off.
    """

    def listener(self) -> BaseConnIter:
        """
        How to get new connections. Returns a BaseConnIter.

        Must be implemented in your subclass.
        """
        raise NotImplementedError

    def wrapper(self, conn) -> BaseMsg:
        """
        How to wrap the connection so that you can communicate on it.

        By default, use `~moat.lib.stream.serial_stack`.
        """
        # pylint:disable=import-outside-toplevel
        from moat.lib.stream import serial_stack  # noqa: PLC0415

        return serial_stack(conn, self.cfg)

    async def reject(self, conn: BaseBuf):
        """
        Close the connection.
        """
        # an async context should do it
        async with conn:
            pass

    async def handler(self, conn):
        """
        Process a connection
        """
        from moat.lib.rpc.cmd.msg import (  # noqa: PLC0415
            ExtCmdMsg,  # pylint:disable=import-outside-toplevel
        )

        app = ExtCmdMsg(self.cfg, self.wrapper(conn), is_server=True)
        if (
            self.app is None
            # or not await self.app.is_ready()
            or self.cfg.get("replace", True)
        ):
            if self.app is not None:
                await self.app.stop()
            app.attached(self, "_")
            self.app = app
            await self.start_app(app)
            if L:
                self.set_ready()
                await app.wait_ready()

            await app.wait_stopped()
            if self.app is app:
                self.app = None
        else:
            # close the thing
            await self.reject(conn)

    async def task(self) -> None:
        """
        Accept connections.
        """
        tg = self.tg
        if tg is None:
            raise RuntimeError("No taskgroup")
        tg = cast("_TaskGroupProto", tg)
        listener = cast("Callable[[], BaseConnIter]", self.listener)
        async with listener() as conns:
            async for conn in conns:

                async def _handle(conn=conn) -> None:
                    await self.handler(conn)

                tg.start_soon(_handle)


class BaseListenCmd(BaseSubCmd):
    """
    An app that runs a listener and connects all incoming connections
    to numbered subcommands.

    Override `listener` to return an async context manager / iterator.
    """

    seq = 1

    # no multiple inheritance for MicroPython
    listener = BaseListenOneCmd.listener
    wrapper = BaseListenOneCmd.wrapper

    async def handler(self, conn):
        """
        Process a new connection.
        """
        from moat.lib.rpc.cmd.msg import (  # noqa: PLC0415
            ExtCmdMsg,  # pylint:disable=import-outside-toplevel
        )

        wrapper = cast("Callable[[object], BaseMsg]", self.wrapper)
        conn = wrapper(conn)
        app = ExtCmdMsg(self.cfg, conn, is_server=True)
        seq = self.seq
        if seq > len(self.sub) * 3:
            seq = 10
        while seq in self.sub:
            seq += 1
        self.seq = seq + 1
        await self.attach(seq, app)
        await self.start_app(app)
        if L:
            await app.wait_ready()

        await app.wait_stopped()
        await self.detach(seq)

    async def task(self) -> None:
        """
        Accept connections.
        """
        tg = self.tg
        if tg is None:
            raise RuntimeError("No taskgroup")
        tg = cast("_TaskGroupProto", tg)
        listener = cast("Callable[[], BaseConnIter]", self.listener)
        async with listener() as conns:
            if L:
                self.set_ready()
            async for conn in conns:

                async def _handle(conn=conn) -> None:
                    await self.handler(conn)

                tg.start_soon(_handle)
