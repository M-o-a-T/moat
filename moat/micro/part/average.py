"""
exponential moving average
"""

from __future__ import annotations

from math import exp

from moat.micro.cmd.base import BaseCmd
from moat.util.compat import Event, ticks_diff, ticks_ms

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.lib.cmd.msg import Msg


class Average(BaseCmd):
    """
    This is an exponential moving average.

    Iterating it yields a new value whenever the input changes.

    Config:
      t: filter reaction time constant, in seconds. Must be given.
      init: initial value
      age: age of the initial value, in seconds; higher = less weight
    """

    flag: Event | None = None

    def __init__(self, cfg):
        super().__init__(cfg)
        if "t" not in self.cfg:
            raise ValueError("Average: need react time constant")
        self._value = cfg.get("init", None)
        self._t = None if self._value is None else ticks_ms() - cfg.get("age", self.cfg["t"])
        self.flag = Event()

    def in_value(self, val, t=None):
        "update value"
        if t is None:
            tn = ticks_ms()
            t = ticks_diff(tn, self._t)
            self._t = tn
        if self._value is not None:
            val = self._value + (1 - exp(-t / 1000 / self.cfg["t"])) * (val - self._value)

        self._value = val
        self._t = t
        self.flag.set()
        self.flag = Event()

    doc_r = dict(_d="read", t="int:last timestamp", _r="float:current avg")

    async def stream_r(self, msg: Msg):
        "read. Wait for change if timestamp didn't change"
        if self._t is None or msg.get("t", None) == self._t:
            await self.flag.wait()
        if msg.can_stream:
            async with msg.stream_out(t=self._t) as m:
                while True:
                    await m.send(self._value)
                    await self.flag.wait()
        else:
            await msg.result(self._value, t=self._t)

    doc_w = dict(_d="write", _0="float:update avg")

    async def stream_w(self, msg):
        "update"
        if msg.can_stream:
            async with msg.stream_in() as mon:
                async for m in mon:
                    self.in_value(m[0], m.get("t", None))
        else:
            self.in_value(msg[0], msg.get("t", None))
        await msg.result()
