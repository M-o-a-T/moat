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

    The listener is wrapped in a :class:`~moat.lib.rpc.ListenerLink` so that
    the resulting stream stack can be reconnected when the underlying
    transport drops.  This allows a :class:`~moat.lib.stream.ReliableMsg`
    layer (when ``lossy`` is set) to resume where it left off.

    Override `listener` to return the connection iterator.
    Override `wrapper` to customise the stream stack.
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

        When ``lossy`` is set in the config, a single :class:`CmdMsg` is used
        with a :class:`~moat.lib.rpc.ListenerLink` underneath.  The
        :class:`~moat.lib.stream.ReliableMsg` layer (added by
        :func:`~moat.lib.stream.serial_stack`) reconnects automatically when
        the underlying transport drops.

        Without ``lossy``, the classic per-connection approach is used:
        each incoming connection gets its own :class:`ExtCmdMsg`.
        """
        tg = self.tg
        if tg is None:
            raise RuntimeError("No taskgroup")
        tg = cast("_TaskGroupProto", tg)

        link_cfg = self.cfg.get("link", {})
        if link_cfg.get("lossy", None):
            # Stream-based approach: one CmdMsg with ListenerLink + ReliableMsg.
            # ReliableMsg handles reconnection via its _run loop.
            from moat.lib.rpc.cmd.msg import CmdMsg  # noqa: PLC0415
            from moat.lib.rpc.conn.util import ListenerLink  # noqa: PLC0415

            listener = cast("Callable[[], BaseConnIter]", self.listener)
            link = ListenerLink(listener())
            stack = self.wrapper(link)
            app = CmdMsg(self.cfg, stack)
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
            # Classic per-connection approach.
            listener = cast("Callable[[], BaseConnIter]", self.listener)
            async with listener() as conns:
                # The listener's __aenter__ blocks until the port is assigned.
                if isinstance(conns.port, int):
                    self.cfg["port"] = conns.port
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
            # The listener's __aenter__ blocks until the port is assigned.
            if isinstance(conns.port, int):
                self.cfg["port"] = conns.port
            if L:
                self.set_ready()
            async for conn in conns:

                async def _handle(conn=conn) -> None:
                    await self.handler(conn)

                tg.start_soon(_handle)
