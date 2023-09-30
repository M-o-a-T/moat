"""
fake sensors
"""

import random
from math import exp, tanh

from moat.micro.compat import Event
from moat.micro.cmd.base import BaseCmd

PINS = {}


class PIN(BaseCmd):
    """
    This is a fake Pin.
    """

    def __init__(self, cfg, **kw):
        PINS[cfg.pin] = self
        self.flag = Event()
        self._value = False

    def in_value(self, val):
        self.flag.set()
        self._value = val

    @property
    def value(self):
        return self._value

    async def __aenter__(self):
        self.flag.set()
        self.flag = Event()

    async def __aexit__(self, *err):
        pass

    def __aiter__(self):
        return self

    async def __anext__(self):
        await self.flag.wait()
        return self._value

    async def run(self, cmd):
        pass

    async def cmd_r(self):
        return self._value

    async def cmd_w(self, v):
        if self._value != v:
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
    - border: A hint for how long the sequence is likely to be close to
      the min/max. Float. Default 2.
    - seed: used to reproduce the random sequence.
    """

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        cfg = self.cfg
        self.min = cfg.min if "min" in cfg else 0
        self.max = cfg.max if "max" in cfg else 1
        self.border = cfg.border if "border" in cfg else 2
        self.step = cfg.step / (self.max - self.min) / 2 if "step" in cfg else 0.1

        seed = cfg.seed if "seed" in cfg else random.random()

        self.val = 0
        self.bias = 0
        self.rand = random.Random(cfg.seed if "seed" in cfg else None)

    async def cmd_r(self):
        b = self.bias + (self.rand.random() - 0.5) * self.step
        v = self.val + b
        if v > self.border and b > 0:
            b = 0
        elif v < -self.border and b < 0:
            b = 0

        self.val = v
        self.bias = b

        # tanh is steeper
        return self.min + (self.max - self.min) * (0.5 + 0.5 * tanh(v))
        # return self.min + (self.max-self.min) / (1+exp(v))
