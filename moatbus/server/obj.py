
# encapsulates one bus participant

from weakref import ref
import outcome

class Obj:
    """
    Encapsulates one bus participant.
    """
    def __init__(self, serial):
        self.serial = serial
        self.master = None

        self._req = None
        self._res = None

    def __repr__(self):
        r=""
        if self.master:
            try:
                dev = self.master.bus_id(self)
            except AttributeError:
                dev = "-"
            return f"<{self.__class__.__name__}: {self.serial} {dev}@{self.master}>"
        else:
            return f"<{self.__class__.__name__}: {self.serial}>"

    def attach(self, master):
        self.detach()

        self.master = ref(master)
        master.register(self)

    def detach(self, master=None):
        """
        This device is no longer on this (or indeed any) bus
        """
        if self.master is not None:
            m,self.master = self.master(), None
            if m is not None and (master is None or m != master):
                m.unregister(self)

    async def request(self, dest:int, code: int, data: bytes, prio:int=0):
        """
        Send a request to the device, wait for a reply
        """
        if self._req is not None:
            raise RuntimeError("Cannot do concorrent requests yet")
        self._req = trio.Event()
        await self.master.send(master.id,dest,code,data, prio=prio)

        try:
            with trio.fail_after(10):
                await self._req.wait()
        finally:
            self._req = None
        res,self._res = self._res,None
        return res.unwrap()

    def has_result(self, res):
        self._req.set()
        self._res = outcome.Value(res)

    @property
    def seen(self):
        """
        Flag whether this obj 
        """
        return self.bus_id is not None
        
