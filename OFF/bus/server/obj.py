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


class BaseObj:
    """
    Encapsulates one bus participant.

    Override this.
    """

    server = None
    client_id = None
    serial = None
    working_until = None
    polled: bool = False  # poll bit (in address request) is set

    def __init__(self, serial, create=None):
        if self.serial is not None:
            return  # already done

        if not isinstance(serial, bytes):
            l = serial.bit_length()
            l = (l + 7) / 8
            serial = serial.to_bytes(l, "big")

        self.serial = serial
        self.is_ready = trio.Event()

    def __repr__(self):
        r = ""
        if self.client_id:
            return f"<{self.__class__.__name__}: {self.serial} @{self.client_id}>"
        else:
            return f"<{self.__class__.__name__}: {self.serial}>"

    @property
    def working(self):
        if self.working_until is None:
            return True
        else:
            return self.working_until > trio.current_time()

    @property
    def server(self):
        return self._server()

    async def attach(self, server):
        """
        Attach me to this server.
        """
        await self.detach()
        self._server = ref(server)

    async def detach(self, server=None):
        """
        Detach me from my server.

        This device is no longer connected to this server.

        If you override this: MUST be idempotent, MUST call superclass.
        """
        self._server = None

    async def msg_in(self, cmd: int, broadcast: bool, data: bytes):
        """
        Process a message from this device.

        Override this.
        """
        pass

    async def msg_out(self, code: int, data: bytes, *, src: int = None, dst: int = None):
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

    async def new_addr(self):
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
    """

    pass
