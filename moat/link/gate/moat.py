"""
MoaT gateway
"""

from __future__ import annotations

import anyio

from moat.link.client import LinkCommon
from ._node import GateNode
from moat.util import Path

class GateNode:
    def __init__(self, gate:GateMoat, path:Path, node: Node):
        self.gate=gate
        self.path=path
        self.node=node

    @property
    def d(self):
        return self.node.data

    def __repr__(self):
        return f"{self.__class__.__name__}:self.d."


class GateMoat:
    def __init__(self, client:LinkCommon, path:Path):
        self._client = client
        self._path = path
        self._data = Node()

    async def run(self, *, task_status):
        """Run the gateway."""
        async with anyio.create_task_group() as tg:
            await tg.start(self.readme)

if TYPE_CHECKING:
    from typing import Awaitable
    from moat.lib.cmd import Msg

