"""
Module for pins
"""

from __future__ import annotations

import machine as M

from moat.compat import AC_use, Event, TaskGroup, sleep_ms
from moat.micro.cmd.base import BaseCmd


class _ADC(M.ADC):
    def __new__(cls, cfg, **kw):
        kw["id"] = M.Pin(cfg["pin"])
        self = super().__new__(**kw)
        return self

    def __init__(self, cfg, **kw):  # noqa:ARG002
        self.t = cfg.get("t", 1000)
        self.nn = cfg.get("nn", 1)
        self.dly = cfg.get("delay", 1)
        self.factor = cfg.get("factor", 1) / self.n / self.nn
        self.offset = cfg.get("offset", 0)

        self.val = 0
        self.evt = Event()
        self.delta = cfg.get("delta", 3)

    async def scan(self):
        self.val = await self.read()
        self.evt.set()
        self.evt = Event()

        while True:
            await sleep_ms(self.t)
            v = await self.read()
            ov, self.val = self.val, v
            if abs(ov - v) >= self.delta:
                self.evt.set()
                self.evt = Event()

    async def read(self):
        c = 0
        for a in range(self.nn):
            if a:
                await sleep_ms(self.dly)
            for _ in range(self.n):
                c += self.read_u16()
        res = c * self.factor + self.offset
        return res

    async def __aenter__(self):
        return self

    async def __aexit__(self, *err):
        pass

    def __aiter__(self):
        return self

    async def __anext__(self):
        await self.evt.wait()
        return self.val


class ADC(BaseCmd):
    """
    This is a basic analog input.

    Iterating it yields a new value whenever the value changes by a given
    threshold.
    """

    def __init__(self, cfg):
        super().__init__(cfg)
        kw = {}
        if "ts" in cfg:
            kw["sample_ns"] = int(cfg["ts"] * 1000000)
        if "atten" in cfg:
            kw["atten"] = cfg["atten"]
        self.adc = _ADC(cfg, **kw)

    async def setup(self):
        "initialization, triggers change"
        await super().setup()
        if getattr(self, "tg", None) is None:
            self.tg = await AC_use(self, TaskGroup())
        await self.tg.spawn(self.pin.scan)

    doc_r = dict(_d="read", o="any:wait for val to not be this", d="int:delta")

    async def cmd_r(self, o: int | None = None, d: int = 0):
        "read. Wait for change if @o (old value) is not None"
        if o is not None and abs(self.adc.val - o) > d:
            await self.adc.evt.wait()
        return self.adc.val
