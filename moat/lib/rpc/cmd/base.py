"""
Basic command handling in MoaT-RPC.
"""

from __future__ import annotations

from ._base import BaseCmd as BaseCmd
from ._base import LoadCmd as LoadCmd
from ._base import LockBaseCmd as LockBaseCmd
from ._base import RootCmd as _RootCmd

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.lib.path import Path


class RootCmd(_RootCmd):
    """
    This is the system's root dispatcher.

    This class ducktypes :py:class:`BaseCmd`.
    """

    def __init__(self, cfg, sig=False, **kw):
        super().__init__(cfg, **kw)
        self.sig = sig

    async def setup(self):
        "Root setup: adds signal handling if requested"
        await super().setup()

        if self.sig:

            async def sig_handler():
                import anyio  # noqa: PLC0415
                import signal  # pylint:disable=import-outside-toplevel  # noqa: PLC0415

                with anyio.open_signal_receiver(
                    signal.SIGINT,
                    signal.SIGTERM,
                    signal.SIGHUP,
                ) as signals:
                    async for _ in signals:
                        self.tg.cancel()
                        break  # default handler on next

            await self.tg.spawn(sig_handler, _name="sig")

    def cfg_at(self, p: Path):
        "returns a CfgStore object at this subpath"
        from moat.lib.rpc.cmd.tree.dir import CfgStore  # noqa:PLC0415

        return CfgStore(self, p)
