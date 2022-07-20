#
import asyncdbus.service as dbus

from moat.compat import CancelledError, sleep_ms, wait_for_ms, ticks_ms, ticks_diff, ticks_add, TimeoutError, Lock, TaskGroup
from moat.util import ValueEvent, combine_dict, attrdict

from .cell import Cell
from .packet import *


class NoSuchCell(RuntimeError):
    pass

class SpuriousData(RuntimeError):
    pass


class Controller(dbus.ServiceInterface):
    """
    Main controller for our BMS.

    TODO really support more than one battery
    """
    def __init__(self, name, cfg, gcfg):
        super().__init__("org.m-o-a-t.bms")
        self.name = name
        self.cfg = cfg
        self.gcfg = gcfg
        self.batt = []
        self.cells = []

        # talk to the cell modules
        self.seq = 0
        self.t = ticks_ms()
        self.w_lock = Lock()
        self.baud = gcfg.apps[cfg.serial].cfg.baud
        self.waiting = [None]*8

        n = 0
        for b in cfg.batteries:
            batt = Battery(self, b, gcfg, n)
            self.batt.append(batt)
            n += b.n

    def add_cell(self, cell):
        self.cells.append(cell)

    async def run(self, req, dbus):
        self._req = req
        self._dbus = dbus

        try:
            await dbus.export('/bms',self)
            await self._run()
        finally:
            await dbus.unexport('/bms')

    @property
    def dbus(self):
        return self._dbus

    @property
    def req(self):
        return self._req

    async def _run(self):
        async with TaskGroup() as tg:
            await tg.spawn(self._read)
            for b in self.batt:
                await tg.spawn(b.run)


    async def send(self, *a,**k):
        """
        Send a message to the cells.
        Returns the per-battery replies.

        Retries a few times before erroring out.
        """

        err = None
        for n in range(5):
            try:
                return await self._send(*a,**k)
            except TimeoutError as e:
                if err is None:
                    err = e
        raise err from None

    async def _send(self, pkt, start=None, end=None, broadcast=False):
        """
        Send a message to the cells.
        Returns the per-battery replies.

        May time out.
        """
        # "broadcast" means the request data is not deleted.
        # start=None requires broadcast.
        # end!=start and len(pkt)==1 requires broadcast IF the packet
        # actually contains data.

        if not isinstance(pkt,(list,tuple)):
            pkt = (pkt,)
        h = PacketHeader(command=pkt[0].T, start=start or 0, broadcast=broadcast)
        for p in pkt[1:]:
            if p.T != h.command:
                raise ValueError("Needs same type, not %s vs %s", pkt[0], p)

        if start is None or broadcast:
            if len(pkt) != 1 or not broadcast:
                raise RuntimeError("Broadcast means one message")
            h.cells = MAXCELLS-1
        elif end is not None:
            h.cells = end-start
            if pkt[0].S.size > 0 and len(pkt) != h.cells+1:
                raise ValueError("Wrong packet count, %d vs %d for %s" % (len(pkt), h.cells+1, pkt[0]))
        else:
            h.cells = len(pkt)-1
        msg = b"".join(p.to_bytes() for p in pkt)

        async with self.w_lock:
            t = ticks_ms()
            td = ticks_diff(self.t,t)
            if td > 0:
                await sleep_ms(td)

            h.sequence = seq = self.seq
            self.seq += 1
            e = self.waiting[seq]
            if e is not None:
                # kill prev request
                e.set_error(TimeoutError)
            self.waiting[seq] = evt = ValueEvent()

            # We need to delay by whatever the affected cells add to the
            # message, otherwise the next msg might catch up
            msg = h.to_bytes()+msg
            n_cells = end-start+1
            mlen = len(msg) + n_cells*(replyClass[h.command].S.size+h.S.size+4)

            self.t = t + 10*mlen/self.baud
            await self.req.send([self.cfg.serial, "send"], data=msg)

        return await wait_for_ms(5000, evt.get)

    async def _read(self):

        def set_err(hdr, err):
            n,self.waiting[hdr.sequence] = self.waiting[hdr.sequence],None
            n.set_error(err)

        req = self._req

        while True:
            msg = await req.send(["local",self.cfg.serial,"pkt"])
            # TODO set up a subscription mechanism

            off = PacketHeader.S.size
            hdr = PacketHeader.from_bytes(msg[0:off])
            if not hdr.seen:
                set_err(hdr, NoSuchCell(hdr.start))
                continue
            RC = replyClass[hdr.command]
            RCL = RC.S.size
            pkt = []
            if hdr.broadcast:
                # The request header has not been deleted,
                # so we need to skip it
                off += RC.S.size
            if RCL:
                while off < len(msg):
                    if off+RCL > len(msg):
                        break  # incomplete
                    pkt.append(RC.from_bytes(msg[off:off+RCL]))
                    off += RCL
            if off != len(msg):
                set_err(hdr, SpuriousData(msg))
                continue
            n,self.waiting[hdr.sequence] = self.waiting[hdr.sequence],None
            if n is not None:
                n.set((hdr,pkt))




class Battery(dbus.ServiceInterface):
    # global battery state, reported via MOAT callback
    u:float = None
    i:float = None
    w:float = None
    n_w:float = 0


    w_past:float = 0
    nw_past:float = 0

    def __init__(self, ctrl, cfg, gcfg, start):
        super().__init__("org.m-o-a-t.bms")

        self.name = cfg.name
        self.ctrl = ctrl
        try:
            self.bms = gcfg.apps[cfg.bms]
        except AttributeError:
            self.bms = attrdict()

        self.start = start
        self.end = start+cfg.n-1

        self.cfg = cfg
        self.gcfg = gcfg

        self.cells = []
        for c in range(cfg.n):
            try:
                ccfg = cfg.cells[c]
            except IndexError:
                ccfg = {}
            ccfg = combine_dict(ccfg, cfg.default, cls=attrdict)
            cell = Cell(self, nr=self.start+c, path=f"/bms/{self.name}/{c}", cfg=ccfg, bcfg=self.cfg, gcfg=gcfg)
            self.ctrl.add_cell(cell)
            self.cells.append(cell)

    async def run(self):
        dbus = self.ctrl.dbus

        await dbus.export(f'/bms/{self.cfg.name}',self)
        for c in self.cells:
            await c.export(self.ctrl.dbus)

        try:
            await self._run()
        finally:
            for v in self.cells:
                await c.unexport()
            await dbus.unexport(f'/bms/{self.cfg.name}')

    async def _run(self):
        async with TaskGroup() as tg:
            await tg.spawn(self._read_update)

            res = await self.send(RequestIdentifyModule())
            res = await self.send(RequestGetSettings())
            from pprint import pprint
            pprint(res)
            raise SystemExit(0)


    async def send(self, pkt, start=None, end=None, **kw):
        """
        Send a message to "my" cells.
        """
        if start is None:
            start = self.start
        if end is None:
            end = self.end
        return await self.ctrl.send(pkt,start=start, end=end, **kw)

    async def _read_update(self):
        try:
            bms = self.cfg.bms
        except AttributeError:
            return  # no global BMS today
        while True:
            msg = await self.ctrl.req.send(["local",self.cfg.bms,"data"])
            await self.update_global(**msg)
            

    async def update_global(self, u=None,i=None,n=None,w=None,**kw):
        if u is not None:
            self.u = u

        if i is not None:
            self.i = i

        if w is not None:
            if n < self.n_w:
                self.w_past += self.w
                self.nw_past += self.n_w
            self.w = w
            self.n_w = n


