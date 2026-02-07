"""
fake sensors
"""

from __future__ import annotations

import random
from math import atanh, tanh

from moat.util import NotGiven
from moat.lib.micro import Event, TaskGroup
from moat.lib.rpc import BaseCmd

PINS = {}


class Pin(BaseCmd):
    """
    This is a fake Pin.

    Iterating it yields a new value whenever the pin changes.
    """

    doc = dict(_c=dict(_d="A fake I/O pin", pin="int:pin#"))

    flag: Event | None = None

    def __init__(self, cfg):
        super().__init__(cfg)
        PINS[cfg["pin"]] = self
        self._value = cfg.get("init", False)
        self.flag = Event()

    def in_value(self, val):
        "set+send pin value unconditionally"
        self.flag.set()
        self.flag = Event()
        self._value = val

    @property
    def value(self):
        "current pin value"
        return self._value

    def __aiter__(self):
        return self

    async def get(self):
        "Wait for + get the next value"
        await self.flag.wait()
        return self._value

    async def cmd(self, val: bool = NotGiven) -> None | bool:
        "Simple Data protocol."
        if val is NotGiven:
            return self.value
        self.in_value(val)

    async def stream(self, msg):
        """
        R/W data stream. The initial argument says whether you want to
        read. Waits for change if @o (old value) is not None.
        """
        o = msg.get("o", None)
        async with TaskGroup() as tg, msg.stream() as m:

            async def _rd():
                val = self.value
                if o is not val:
                    await m.send(val)
                while True:
                    val = await self.get()
                    await m.send(val)

            if o is not None or msg.get(0, False):
                tg.start_soon(_rd)

            for mm in m:
                self.in_value(mm[0])
            tg.cancel()
            await msg.result()


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

    doc = dict(
        _c=dict(
            _d="A random analog input",
            min="float:min value",
            max="float:max value",
            border="float:border",
            seed="int:random seed",
        )
    )

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
