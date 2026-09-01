# noqa:D100
from __future__ import annotations

from contextlib import asynccontextmanager

from moat.util import NotGiven
from moat.bus.backend import BaseBusHandler, UnknownParamError
from moat.bus.message import BusMessage
from moat.lib.codec.moat_cbor import Codec as StdCBOR
from moat.lib.path import P
from moat.link.backend.mqtt import Backend

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


class Handler(BaseBusHandler):
    """
    This handler connects directly to MQTT. In contrast, the DistKV handler
    tunnels through DistKV.
    """

    short_help = "Connect via MQTT"

    cfg: Any
    name: str | None
    _mqtt: Any = None
    _mqtt_it: Any
    id: Any

    def __init__(self, cfg: Any, name: str | None = None) -> None:
        super().__init__(cfg)
        self.cfg = cfg
        self.name = name

    PARAMS = {
        "id": (
            str,
            "connection ID (unique!)",
            lambda x: len(x) > 7,
            NotGiven,
            "must be at least 8 chars",
        ),
        "uri": (
            str,
            "MQTT broker URL",
            lambda x: "://" in x and not x.startswith("http"),
            "mqtt://localhost",
            "must be a Broker URL",
        ),
        "topic": (
            P,
            "message topic",
            lambda x: len(x) > 1,
            NotGiven,
            "must be at least two elements",
        ),
    }

    @classmethod
    def check_config(cls, cfg: dict[str, Any]) -> None:
        """Validate configuration."""
        for k, _v in cfg.items():
            if k not in ("id", "uri", "topic"):
                raise UnknownParamError(k)
            # TODO check more

    @asynccontextmanager
    async def _ctx(self) -> AsyncIterator[Handler]:
        async with (
            Backend(self.cfg.mqtt, name=self.name) as C,
            C.monitor(self.cfg.topic, codec=StdCBOR()) as CH,
        ):
            self._mqtt = CH
            yield self

    def __aiter__(self) -> Handler:
        self._mqtt_it = self._mqtt.__aiter__()
        return self

    async def __anext__(self) -> BusMessage:
        while True:
            msg = await self._mqtt_it.__anext__()
            msg = msg.payload
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
        """Send a message via MQTT."""
        data: dict[str, Any] = {k: getattr(msg, k) for k in msg._attrs}  # noqa:SLF001
        data["_id"] = getattr(msg, "_mqtt_id", self.id)
        await self._mqtt.send(topic=self.cfg.topic, message=data)
