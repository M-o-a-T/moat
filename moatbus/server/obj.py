
# encapsulates one bus participant

from weakref import ref
import outcome
import trio

class NoServerError(RuntimeError):
    """
    This object doesn't have a server
    """

class NoClientError(RuntimeError):
    """
    This client hasn't been seen
    """

_obj_reg = {}  # id > obj


def register_obj(obj):
    """
    Register this object.
    It must already have a serial#.
    """
    assert obj.serial is not None
    try:
        oobj = _obj_reg[obj.serial] = obj
    except KeyError:
        pass
    else:
        assert isinstance(oobj, Obj)
        assert not isinstance(obj, Obj)
    _obj_reg[obj.serial] = obj


class BaseObj:
    """
    Encapsulates one bus participant.

    Override this.
    """
    server = None
    client_id = None
    serial = None
    is_new = True
    working = False
    polled: bool = False # poll bit (in address request) is set

    def __init__(self, serial, create=None):
        if self.serial is not None:
            return # already done

        if not isinstance(serial,bytes):
            l = serial.bit_length()
            l = (l+7)/8
            serial = serial.to_bytes(l,"big")

        self.serial = serial
        self.is_ready = trio.Event()

    def __repr__(self):
        r=""
        if self.server:
            try:
                dev = self.server.bus_id(self)
            except AttributeError:
                dev = "-"
            return f"<{self.__class__.__name__}: {self.serial} {dev}@{self.server}>"
        else:
            return f"<{self.__class__.__name__}: {self.serial}>"

    def attach(self, server):
        """
        Attach me to this server.
        """
        self.detach()

        self.server = ref(server)
        server.register(self)
        assert self.client_id is not None
        return self.client_id

    def detach(self, server=None):
        """
        Detach me from my server.

        This device is no longer on this (or indeed any) bus
        """
        if self.server is not None:
            m, self.server = self.server(), None
            if m is not None and (server is None or m != server):
                m.deregister(self)

    async def msg_in(self, cmd:int, broadcast:bool, data:bytes):
        """
        Process a message from this device.

        Override this.
        """
        pass

    async def msg_out(self, code:int, data:bytes, *, src:int=None, dst:int=None):
        """
        Send a message to the device.
        """
        m = self.server
        if not m:
            raise NoServerError()
        m = m()
        if not m:
            raise NoServerError()
        if self.client_id is None:
            raise NoClientError()

        if src is none:
            src = m.id
        if dst is none:
            dst = self.client_id
        await m.send(src=src, dst=dst, code=code, data=data)

    async def new_adr(self):
        """
        Called from the server when the device has been assigned an
        address.

        This method should not delay too long; it must be idempotent and
        cannot communicate with the device.

        Override this, call when done.
        """
        self.is_ready.set()

    async def poll_start(self, duration):
        """
        Called when a poll message arrives from the device.

        "duration" is the time in seconds until the device turns itself
        off.

        This message may arrive, hence this method may be called, during
        such a timespan. The old end time must be discarded.
        """

    @property
    def seen(self):
        """
        Flag whether this obj is on some bus
        """
        return self.bus_id is not None
        

class Obj(BaseObj):
    """
    This type is used when the system sees a device it doesn't know.

    The `__new__` method will return the existing object, if any.
    """
    def __new__(cls, serial, create=None):
        if not isinstance(serial,bytes):
            l = serial.bit_length()
            l = (l+7)/8
            serial = serial.to_bytes(l,"big")
        try:
            obj = _obj_reg[serial]
        except KeyError:
            if create is False:
                raise
            return super().__new__(cls)
        else:
            if create:
                raise KeyError(serial)
            return obj

get_obj=Obj
