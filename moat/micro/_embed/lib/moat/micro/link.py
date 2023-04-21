"""
Helper to hot-wire a command to read data from/to the other side.
"""

from moat.util import OptCtx  # pylint:disable=no-name-in-module

from moat.micro.compat import (  # pylint: disable=redefined-builtin,no-name-in-module
    Event,
    TimeoutError,
    idle,
    wait_for_ms,
)


class Reader:
    """
    Base class for something that reads data.

    The "send" method forwards to the other side.
    """

    _link = None
    __cmd = None

    def __init__(self, cfg, **_kw):
        self._link = cfg.get("link", None)

    async def run(self, cmd):
        "background worker"
        reg = cmd.base.register(self, cmd.name, self._link) if self._link is not None else None
        with OptCtx(reg):
            await idle()

    async def read(self):
        "read-and-send"
        res = await self.read_()
        await self.send(res)
        return res

    async def read_(self):
        "the actual `read()` function` you need to override"
        raise NotImplementedError("Reader")

    async def send(self, msg):
        "send to the remote side; called by `read`"
        if self._link is None:
            return
        if self.__cmd is None:
            return
        await self.__cmd.send_nr("s", o=(self.__cmd.name, self._link), d=msg)


class Listener(Reader):
    """
    Link object that listens to a specific message from the other side.

    Reading returns the latest/next message.
    """

    # pylint: disable=abstract-method

    _cmd = None
    _up = None
    _rd = None
    #  _link = None  # BaseReader

    def __init__(self, cfg, **kw):
        super().__init__(cfg, **kw)
        self._up = Event()

    async def run(self, cmd):
        "hook a monitor to the base watcher"
        self._up.set()
        if cmd is None:
            return
        if self._link is None:
            return
        self._rd = aiter(cmd.base.watch(cmd.name, self._link))
        self._cmd = cmd
        try:
            await idle()
        finally:
            self._rd.close()

    async def read(self, t=100):
        """
        Wait for new data.
        If none arrive after 1/10th second, poll the remote side.

        If this method is called before "run", it waits for that to start.
        """
        if self._rd is not None:
            await self._up.wait()
            del self._up

        try:
            return await wait_for_ms(t, anext, self._rd)
        except TimeoutError:
            await self._cmd.send("sq", o=(self._cmd.name, self._link))

    async def send(self, msg):
        """
        don't send: we received it!
        """
        pass  # pylint:disable=unnecessary-pass
