# noqa:D100
from __future__ import annotations

from contextlib import asynccontextmanager

from moat.bus.message import BusMessage
from moat.lib.path import P, Path

from . import BaseBusHandler, UnknownParamError

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from moat.kv.client import Client

    from collections.abc import AsyncIterator


class Handler(BaseBusHandler):
    """
    This handler tunnels through MoaT-KV. In contrast, the MQTT handler
    connects directly.
    """

    short_help = "tunnel through MoaT-KV"

    client: Client
    topic: Path
    _mqtt: Any
    _mqtt_it: Any
    id: Any

    def __init__(self, client: Client, topic: Path) -> None:
        super().__init__(client)
        self.client = client
        self.topic = topic

    PARAMS = {
        "topic": (
            P,
            "Topic for messages",
            lambda x: len(x) > 1,
            None,
            "must be at least two elements",
        ),
    }

    @classmethod
    def check_config(cls, cfg: dict[str, Any]) -> None:
        """Validate configuration."""
        for k, v in cfg.items():
            if k != "topic":
                raise UnknownParamError(k)
            if not isinstance(v, Path):
                raise TypeError(k, v)

    @asynccontextmanager
    async def _ctx(self) -> AsyncIterator[Handler]:
        async with self.client.msg_monitor(topic=tuple(self.topic)) as CH:
            self._mqtt = CH
            yield self

    def __aiter__(self) -> Handler:
        self._mqtt_it = self._mqtt.__aiter__()
        return self

    async def __anext__(self) -> BusMessage:
        while True:
            msg = await self._mqtt_it.__anext__()
            try:
                msg = msg.data
            except AttributeError:
                continue
            try:
                id_ = msg.pop("_id")
            except KeyError:
                continue
            else:
                if id_ == self.id:
                    continue
                msg = BusMessage(**msg)
                msg._mqtt_id = id_  # noqa:SLF001
                return msg

    async def send(self, msg: BusMessage) -> None:
        """Send a message via MoaT-KV."""
        data: dict[str, Any] = {k: getattr(msg, k) for k in msg._attrs}  # noqa:SLF001
        data["_id"] = getattr(msg, "_mqtt_id", self.id)
        await self._mqtt.msg_send(topic=self.topic, data=data)
