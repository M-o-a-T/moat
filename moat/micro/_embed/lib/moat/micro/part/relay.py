"""
More common code
"""
from moat.util import NotGiven, attrdict, load_from_cfg

from ..compat import Event, Pin_OUT, TaskGroup, sleep, sleep_ms, ticks_diff, ticks_ms, idle
from ..link import Reader


class Relay(Reader):
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

    def __init__(self, cfg, value=None, force=None, **kw):
        super().__init__(cfg)
        pin = cfg.pin
        if isinstance(pin, int):
            cfg.pin = attrdict(client="moat.micro.part.pin.Pin", pin=pin)
        kw.setdefault("mode", Pin_OUT)
        self.pin = load_from_cfg(cfg.pin, **kw)
        if self.pin is None:
            raise ImportError(cfg.pin)
        self.t = [cfg.get("t_off", 0), cfg.get("t_on", 0)]
        self.note = cfg.get("note", None)

    async def set(self, value=None, force=NotGiven):
        """
        Change relay state.

        The state is set to @force, or @value if @force is None,
        or self.value if @value is None too.

        If you don't pass a @force argument in, the forcing state of the
        relay is not changed.
        """
        if force is NotGiven:
            force = self.force
        else:
            self.force = force

        if value is None:
            value = self.value
        else:
            self.value = value

        if force is None and self._delay is not None:
            return
        await self._set()

    async def _set(self):
        val = self.value if self.force is None else self.force
        if val is None:
            return
        p = await self.pin.get()
        if p == val:
            return

        if self._delay is not None:
            self._delay.cancel()
            self._delay = None
        t = self.t[val]
        if not t:
            return
        self._delay = await self.__tg.spawn(self._run_delay, t)
        await self.pin.set(val)
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

    async def read_(self):
        return dict(
            s=self.value,
            f=self.force,
            d=None if self._delay is None else ticks_diff(ticks_ms(), self.t_last),
        )

    async def run(self, cmd):
        async with TaskGroup() as self.__tg:
            await self.set()
            await self.read()
            self.__tg.start_soon(super().run, cmd)
            await idle()
