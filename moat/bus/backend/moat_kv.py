# noqa:D100
from __future__ import annotations

from contextlib import asynccontextmanager

from moat.util import P, Path

import typing

if typing.TYPE_CHECKING:
    from moat.kv.client import Client

from moat.bus.message import BusMessage

from . import BaseBusHandler, UnknownParamError


class Handler(BaseBusHandler):
    """
    This handler tunnels through MoaT-KV. In contrast, the MQTT handler
    connects directly.
    """

    short_help = "tunnel through MoaT-KV"

    def __init__(self, client: Client, topic: Path):
        super().__init__()
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

    @staticmethod
    def check_config(cfg: dict):  # noqa:D102
        for k, v in cfg.items():
            if k != "topic":
                raise UnknownParamError(k)
            if not isinstance(v, Path):
                raise TypeError(k, v)

    @asynccontextmanager
    async def _ctx(self):
        async with self.client.msg_monitor(topic=self.topic) as CH:
            self._mqtt = CH
            yield self

    def __aiter__(self):
        self._mqtt_it = self._mqtt.__aiter__()
        return self

    async def __anext__(self):
        while True:
            msg = await self._mqtt_it.__anext__()
            try:
                msg = msg.data
            except AttributeError:
                continue
            try:
                id = msg.pop("_id")
            except KeyError:
                continue
            else:
                if id == self.id:
                    continue
                msg = BusMessage(**msg)
                msg._mqtt_id = id  # noqa:SLF001
                return msg

    async def send(self, msg):  # noqa:D102
        data = {k: getattr(msg, k) for k in msg._attrs}  # noqa:SLF001
        data["_id"] = getattr(msg, "_mqtt_id", self.id)
        await self._mqtt.msg_send(topic=self.topic, data=data)
