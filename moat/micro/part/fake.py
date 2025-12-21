"""
fake sensors
"""

from __future__ import annotations

import random
from math import atanh, tanh

from moat.micro.cmd.base import BaseCmd
from moat.util.compat import Event

PINS = {}


class Pin(BaseCmd):
    """
    This is a fake Pin.

    Iterating it yields a new value whenever the pin changes.
    """

    flag: Event | None = None

    def __init__(self, cfg):
        super().__init__(cfg)
        PINS[cfg["pin"]] = self
        self._value = cfg.get("init", False)

    def in_value(self, val):
        "set+send pin value unconditionally"
        self.flag.set()
        self._value = val

    @property
    def value(self):
        "current pin value"
        return self._value

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.flag is None:
            self.flag = Event()
        await self.flag.wait()
        return self._value

    doc_r = dict(_d="read", prev="bool:wait if unchanged")

    async def cmd_r(self, prev=None):
        "read. Wait for change if @prev (previous value) is not None"
        if prev is self._value:
            if self.flag is None:
                self.flag = Event()
            await self.flag.wait()
        return self._value

    doc_w = dict(_d="write", _0="bool:new state")

    async def cmd_w(self, v):
        "set fake pin; trigger iter if changed"
        if self._value != v:
            if self.flag is not None:
                self.flag.set()
                self.flag = Event()
            self._value = v


class ADC(BaseCmd):
    """
    This is a "fake" ADC that walks between a given min and max value.

    The min/max boundary values will never be returned.

    Config parameters:
    - min, max: range. Defaults to 0…1.
    - step: max difference between two consecutive values.
    - border: A hint for how long the sequence should be close to
      the min/max. Float. Default 2.
    - seed: used to reproduce the random sequence.
    """

    def __init__(self, cfg):
        super().__init__(cfg)
        cfg = self.cfg
        self.min = cfg.get("min", 0)
        self.max = cfg.get("max", 1)
        self.border = cfg.get("border", 2)
        self.step = cfg["step"] / (self.max - self.min) / 2 if "step" in cfg else 0.1

        self.val = (
            atanh(((cfg.init - self.min) / (self.max - self.min) - 0.5) * 2)
            if "init" in cfg
            else 0
        )
        self.bias = 0
        try:
            self.rand = random.Random(cfg.get("seed", None))
        except AttributeError:
            from moat.util.random import Random  # noqa: PLC0415

            self.rand = Random(cfg["seed"] if "seed" in cfg else random.getrandbits(32))

    doc_r = dict(_d="read")

    async def cmd_r(self):
        "read current value"
        b = self.bias + (self.rand.random() - 0.5) * self.step
        v = self.val + b
        if v > self.border and b > 0:
            b = 0
        elif v < -self.border and b < 0:
            b = 0

        self.val = v
        self.bias = b

        return self.min + (self.max - self.min) * (0.5 + 0.5 * tanh(v))
