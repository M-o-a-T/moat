"""
Active ping
"""

from __future__ import annotations

from moat.micro.cmd.base import BaseCmd
from moat.util.compat import sleep, wait_for

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.lib.cmd.msg import Msg


class _NotGiven:
    pass


class Cmd(BaseCmd):
    """
    An app to do active ping-ing: keepalive, discover dead links.

    Config:
        t: timeout
        d: delay between pings
        p: Path to call.
        s: flag whether to do streaming.
    """

    doc_ = dict(_d="ping echo")

    async def stream(self, msg: Msg):
        """
        Keepalive/liveness monitor. Echoes incoming data.
        """
        if msg.can_stream:
            async with msg.stream(*msg.args, **msg.kw) as md:
                async for m in md:
                    await msg.send(*m.args, **m.kw)
        await msg.result(*msg.args, **msg.kw)

    async def task(self):  # noqa:D102
        if (p := self.cfg.get("p", None)) is None:
            return await super().task()
        async with self.root.sub_at(p) as sub:
            self.set_ready()
            if self.cfg.get("s", False):
                async with sub.stream() as msg:
                    await self._do(msg.send)
            else:
                self.set_ready()
                await self._do(sub)

    async def _do(self, sender):
        n = 0
        while True:
            res = await wait_for(self.cfg.get("t", 3), sender, n)
            if res != n:
                raise RuntimeError("wrong ping echo: want {n}, got {r !r}")
            n = (n + 1) if n < 9 else 1
            await sleep(self.cfg.get("d", 59))
