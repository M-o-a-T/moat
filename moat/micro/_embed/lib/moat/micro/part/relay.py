"""
More common code
"""

from __future__ import annotations

from moat.util import NotGiven, Path
from moat.lib.codec.errors import StoppedError
from moat.micro.cmd.base import BaseCmd
from moat.util.compat import TaskGroup, sleep_ms, ticks_diff, ticks_ms


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
            raise ValueError("Pin not set")  # noqa:TRY004
        t = cfg.get("t", {})
        self.t = [t.get("off", 0), t.get("on", 0)]
        self.note = cfg.get("note", None)

    async def setup(self):  # noqa:D102
        await super().setup()
        self.pin = self.root.sub_at(self.cfg.pin)
        if await self.pin.rdy_():
            raise StoppedError("pin")
        await self.cmd_w()

    async def run(self):  # noqa:D102
        async with TaskGroup() as self.__tg:
            await super().run()

    doc_w = dict(_d="change", _0="bool:new value", f="bool|None:force?")

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
        """
        Return the current intended state (async version)
        """
        return self.get_sync()

    @property
    def delayed(self):
        "flag whether the relay is delaying a change"
        return self._delay is not None

    doc_r = dict(
        _d="get state",
        _r=dict(
            v="bool:std output", f="bool:forced output", d="int:delay(ms)", p="bool:hardware state"
        ),
    )

    async def cmd_r(self):
        """
        Returns the current state, as a mapping.

        v: currently set value
        f: currently forced value
        d: delay until next change (msec) or None
        p: actual pin state
        """
        p = await self.pin.r()
        return dict(
            v=self.value,
            f=self.force,
            p=p,
            d=None if self._delay is None else ticks_diff(ticks_ms(), self.t_last),
        )
