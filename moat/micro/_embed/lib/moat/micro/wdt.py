"""
Watchdog timer.

Config options:

* timeout

  Minimum time between "ping"s. Zero turns off the watchdog. Depending on
  the hardware you may or may not be able to change this, once it's >0.

* ext

  Require external keepalives.

* hw

  Use the singleton hardware watchdog.

"""
import sys

import machine

import moat.micro.main as M
from moat.micro.cmd import BaseCmd
from moat.micro.compat import Event, TimeoutError, wait_for_ms

try:
    _reset = machine.reset
except AttributeError:  # on Linux?
    import ffi
    C = ffi.open(None)
    def _reset():
        C.func("i","_exit","i")(11)

class WDT:
    """
    A wrapper for hardware/software watchdog Timer(s).

    Config:

        t: timeout in msec
        hw: flag whether to use the hardware watchdog
        ext: flag whether to require external ping from the server
        tt: trigger timeout, defaults to t/2
    """
    wdt = None
    timeout = None
    _ping = None

    def __init__(self, cfg):
        if cfg.get("hw",False):
            if M.WDT is not None:
                raise RuntimeError("one hw watchdog")
            M.WDT = self
        self._ping = Event()
        self._setup(cfg)

    def _setup(self, cfg):
        self.cfg = cfg
        t = cfg.get("t", 0)
        if not t:
            if self.wdt is None:
                self.timeout = 0
        elif self.wdt:
            pass  # can't change or turn off

        else:
            if self.cfg.get("hw"):
                self.wdt = machine.WDT(t)
            self.timeout = t
            self.trigger = self.cfg.get("tt", self.timeout/2)
        self._ping.set()

    async def run(self):
        T = getattr(machine,"Timer",None)
        t = None
        while True:
            if self.cfg.get("ext", False):
                if self.wdt is not None:
                    # wait for external trigger
                    # the HW WDT will kill us if it doesn't arrive
                    await self._ping.wait()
                else:
                    # die hard if the external ping doesn't arrive
                    try:
                        await wait_for_ms(self.timeout, self._ping.wait)
                    except TimeoutError:
                        _reset()
            elif self.wdt is not None:
                # feed the watchdog when the trigger expires
                try:
                    await wait_for_ms(self.trigger, self._ping.wait)
                except TimeoutError:
                    pass
            else:
                # use a software timeout
                if t is None:
                    t = T()
                if t is None:
                    raise RuntimeError("no timer")
                t.init(period=self.timeout, mode=T.ONE_SHOT, callback=lambda x:_reset)
                try:
                    await self._ping.wait()
                finally:
                    t.deinit()

            if self.wdt is not None:
                self.wdt.feed()
            if self._ping.is_set():
                self._ping = Event()

    def ping(self, force=False):
        """
        Keepalive trigger for the watchdog.

        If @force is set, the timer is set directly; if not, the watchdog
        task is woken up.
        """
        if force and self.wdt is not None:
            self.wdt.feed()
        if self._ping is not None:
            self._ping.set()
