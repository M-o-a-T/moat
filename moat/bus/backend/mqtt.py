# noqa:D100
from __future__ import annotations

from contextlib import asynccontextmanager

from moat.util import NotGiven, P, StdCBOR
from moat.bus.backend import BaseBusHandler, UnknownParamError
from moat.bus.message import BusMessage
from moat.link.backend.mqtt import Backend


class Handler(BaseBusHandler):
    """
    This handler connects directly to MQTT. In contrast, the DistKV handler
    tunnels through DistKV.
    """

    short_help = "Connect via MQTT"

    _mqtt = None

    def __init__(self, cfg, name: str | None = None):
        super().__init__()
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

    @staticmethod
    def check_config(cfg: dict):  # noqa:D102
        for k, _v in cfg.items():
            if k not in ("id", "uri", "topic"):
                raise UnknownParamError(k)
            # TODO check more

    @asynccontextmanager
    async def _ctx(self):
        async with (
            Backend(self.cfg.mqtt, name=self.name) as C,
            C.monitor(self.cfg.topic, codec=StdCBOR()) as CH,
        ):
            self._mqtt = CH
            yield self

    def __aiter__(self):
        self._mqtt_it = self._mqtt.__aiter__()
        return self

    async def __anext__(self):
        while True:
            msg = await self._mqtt_it.__anext__()
            msg = msg.payload
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
        await self._mqtt.send(topic=self.cfg.topic, message=data)
