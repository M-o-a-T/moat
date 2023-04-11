"""
Helper to hot-wire a command to read data from/to the other side.
"""

from moat.micro.compat import sleep


class Reader:
    """
    Base class for something that reads data.

    The "send" method forwards to the other side if linked to it.
    """
    _link = None
    __cmd = None

    def __init__(self, cfg, bms=None, **kw):
        self._link = cfg.get("link", None)

    async def run(self, cmd):
        self.__cmd = cmd
        pass

    async def read(self):
        res = await self.read_()
        await self.send(res)
        return res

    async def read_(self):
        raise NotImplementedError("Reader")

    async def send(self, msg):
        if self._link is None:
            return
        if self.__cmd is None:
            return
        await self.__cmd.send_nr([self.__cmd.name, self._link], msg)


class Listener(Reader):
    """
    Link object that listens to a specific message from the other side.

    Reading returns the latest/next message.
    """
    _msg = None
    _evt = None
    #  _link = None  # BaseReader

    async def __recv(self, **msg):
        self._msg = msg
        self._evt.set()

    async def run(self, cmd):
        if cmd is None:
            return
        if self._link is None:
            return
        try:
            setattr(cmd, "cmd_"+self._link, self.__recv)
            while True:
                sleep(9999)
        finally:
            if getattr(cmd, "cmd_"+self._link, None) == self.__recv:  # no, "is" doesn't work here
                delattr(cmd, "cmd_"+self._link)

    async def read(self):
        await self._evt.wait()
        self._evt = Event()
        msg,self._msg = self._msg,None
        return msg

    async def send(self, msg):
        """
        don't send: we received it!
        """
        pass


