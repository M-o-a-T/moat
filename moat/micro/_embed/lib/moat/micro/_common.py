"""
More common code
"""
from moat.util import NotGiven, load_from_cfg, attrdict
from moat.micro.compat import TaskGroup, sleep, sleep_ms, Event, ticks_ms, ticks_diff, Pin_OUT

class _Remote:
    """
    Delegates requests to the other side
    """

    def __init__(self, cmd, cfg, **kw):
        self.req = cmd.request
       
        self.cmd = cfg.cmd
        if isinstance(self.cmd,str):
            self.cmd = self.cmd.split(".")
        self.args = cfg.args if "args" in cfg else {}
        self.attr = cfg.attr if "attr" in cfg else []
    
    async def read(self):
        res = await self.req.send(self.cmd, **self.args)
        for a in self.attr:
            try:
                res = getattr(res,a)
            except AttributeError:
                res = res[a]
        return res


class Relay:
    """
    A relay is an output pin with an overriding "force" state.

    - pin: how to talk to the thing
    - t_on, t_off, minimum non-forced on/off time
    - note: send a message when changed
    """
    _delay = None
    t_last = 0
    value = None
    force = None

    def __init__(self, cfg, value=None, force=None, **kw):
        pin = cfg.pin
        if isinstance(pin,int):
            cfg.pin = attrdict(client="app.part.pin.Pin", pin=pin)
        kw.setdefault("mode", Pin_OUT)
        self.pin = load_from_cfg(cfg.pin, **kw)
        self.t = [cfg.get("t_off",0), cfg.get("t_on",0)]
        self.note = cfg.get("note",None)

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

    async def state(self):
        return dict(
                s=self.value,
                f=self.force,
                d=None if self._delay is None else ticks_diff(ticks_ms(), self.t_last),
            )

    async def run(self, cmd):
        async with TaskGroup() as self.__tg:
            await self.set()
            while True:
                await sleep(9999)



