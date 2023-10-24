"""
More common code
"""
from moat.util import NotGiven, Path

from ..cmd.base import BaseCmd
from ..cmd.util import StoppedError
from ..compat import TaskGroup, sleep_ms, ticks_diff, ticks_ms


class Relay(BaseCmd):
    """
    A relay is an output pin with an overriding "force" state.

    - pin: how to talk to the actual hardware output
    - t_on, t_off, minimum non-forced on/off time
    - note: send a message when changed
    """

    _delay = None
    t_last = 0
    value = None
    force = None

    def __init__(self, cfg):
        super().__init__(cfg)
        if not isinstance(cfg.get("pin", None), (tuple, list, Path)):
            raise ValueError("Pin not set")
        t = cfg.get("t", {})
        self.t = [t.get("off", 0), t.get("on", 0)]
        self.note = cfg.get("note", None)

    async def setup(self):
        if await self.pin.rdy():
            raise StoppedError("pin")
        await self.cmd_w()
        await super().setup()

    async def run(self):
        self.pin = self.root.sub_at(*self.cfg.pin)
        async with TaskGroup() as self.__tg:
            await super().run()

    async def cmd_w(self, v=None, f=NotGiven):
        """
        Change relay state.

        The state is set to @f ("force"), or @v ("value") if @f is None,
        or self.value if @v is None too.

        If you don't pass a @force argument in, the forcing state of the
        relay is not changed.
        """
        if f is NotGiven:
            f = self.force
        else:
            self.force = f

        if v is None:
            v = self.value
        else:
            self.value = v

        if f is None and self._delay is not None:
            return
        await self._set()

    async def _set(self):
        val = self.value if self.force is None else self.force
        if val is None:
            return
        p = await self.pin.r()
        if p == val:
            return

        if self._delay is not None:
            self._delay.cancel()
            self._delay = None
        await self.pin.w(v=val)
        t = self.t[val]
        if not t:
            return
        self._delay = await self.__tg.spawn(self._run_delay, t, _name="Rly")
        self.t_last = ticks_ms()

    async def _run_delay(self, t):
        await sleep_ms(t)
        self._delay = None
        await self._set()

    def get_sync(self):
        """
        Return the current intended state.
        """
        if self.force is not None:
            return self.force
        return self.value

    async def get(self):
        return self.get_sync()

    @property
    def delayed(self):
        return self._delay is not None

    async def cmd_r(self):
        return dict(
            v=self.value,
            f=self.force,
            d=None if self._delay is None else ticks_diff(ticks_ms(), self.t_last),
        )
