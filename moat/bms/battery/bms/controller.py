#
import asyncdbus.service as dbus

from moat.compat import CancelledError, sleep_ms, wait_for_ms, ticks_ms, ticks_diff, ticks_add, TimeoutError, Lock, TaskGroup
from moat.util import ValueEvent, combine_dict, attrdict

from .cell import Cell
from .packet import *

import logging
logger = logging.getLogger("__name__")

class NoSuchCell(RuntimeError):
    pass

class SpuriousData(RuntimeError):
    pass

class MessageLost(RuntimeError):
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
        for i,b in enumerate(cfg.batteries):
            batt = Battery(self, b, gcfg, n,i)
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
            except (TimeoutError,MessageLost) as e:
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
            self.seq = (self.seq + 1) % 8
            evt = self.waiting[seq]
            if evt is not None:
                # wait for prev request to complete
                logger.error("WAIT %d",seq)
                await evt.wait()
            logger.error("SEND %d",seq)
            self.waiting[seq] = evt = ValueEvent()

            # We need to delay by whatever the affected cells add to the
            # message, otherwise the next msg might catch up
            msg = h.to_bytes()+msg
            n_cells = end-start+1
            mlen = len(msg) + n_cells*(replyClass[h.command].S.size+h.S.size+4)

            self.t = t + 10*mlen/self.baud
            await self.req.send([self.cfg.serial, "send"], data=msg)

        res = await wait_for_ms(5000, evt.get)
        return res

    async def _read(self):

        def set_err(seq, err):
            n,self.waiting[seq] = self.waiting[seq],None
            if n is not None:
                n.set_error(err)

        req = self._req

        xseq = 0
        while True:
            msg = await req.send(["local",self.cfg.serial,"pkt"])
            # TODO set up a subscription mechanism

            off = PacketHeader.S.size
            hdr = PacketHeader.from_bytes(msg[0:off])
            while xseq != hdr.sequence:
                set_err(xseq, MessageLost())
                xseq = (xseq+1) & 0x07
            if not hdr.seen:
                set_err(hdr.sequence, NoSuchCell(hdr.start))
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
                set_err(hdr.sequence, SpuriousData(msg))
                continue

            evt, self.waiting[hdr.sequence] = self.waiting[hdr.sequence], None
            if evt is not None:
                evt.set((hdr,pkt))

    @dbus.method
    async def GetNBatteries(self) -> 'y':
        """
        Number of batteries on this controller
        """
        return len(self.batt)


class Battery(dbus.ServiceInterface):
    # global battery state, reported via MOAT callback
    u:float = None
    i:float = None
    w:float = None
    n_w:float = 0

    w_past:float = 0
    nw_past:float = 0

    chg_set:bool = None
    dis_set:bool = None

    def __init__(self, ctrl, cfg, gcfg, start, num):
        super().__init__("org.m-o-a-t.bms")

        self.name = cfg.name
        self.num = num
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

        await dbus.export(f'/bms/{self.num}',self)
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

            res = await self.send(RequestGetSettings())
            if len(res) != len(self.cells):
                raise RuntimeError(f"Battery {self.begin}:{self.end}: found {len(res)} modules, not {len(self.cells)}")

            for c,r in zip(self.cells,res):
                r.to_cell(c)

            await tg.spawn(self.task_keepalive)
            await tg.spawn(self.task_voltage)
            await tg.spawn(self.task_temperature)


    async def task_keepalive(self):
        try:
            t = self.bms.poll.k / 2.1
        except AttributeError:
            return
        while True:
            self.ctrl.req.send([self.cfg.bms,"live"])
            await sleep_ms(t)


    async def task_voltage(self):
        """
        Periodically check the cell voltages
        """
        while True:
            hdr,res = await self.send(RequestVoltages())
            chg = False
            for c,r in zip(self.cells,res):
                chg = r.to_cell(c) or chg
            if chg:
                await self.check_limits()
                await self.VoltageChanged()

            await anyio.sleep(cfg.t.voltage)


    async def check_limits(self):
        """
        Verify that the battery voltages are within spec.
        """
        chg_ok = True
        dis_ok = True

        vsum = sum(c.voltage for c in self.cells)
        if abs(vsum-self.u) > vsum/0.02:
            logger.warning(f"Voltage doesn't match: reported {self.u}, sum {vsum}")

        if self.bms:
            if self.u >= self.bms.cfg.u.ext.max:
                chg_ok = False

            if self.u >= self.bms.cfg.u.max:
                self.ctrl.req.send([self.cfg.bms,"rly", st=False])
                logger.error(f"Battery {self} overvoltage, turned off")

            if self.u <= self.bms.cfg.u.ext.min:
                dis_ok = False

            if self.u <= self.bms.cfg.u.min:
                self.ctrl.req.send([self.cfg.bms,"rly", st=False])
                logger.error(f"Battery {self} undervoltage, turned off")

        for c in cells:
            if c.voltage >= c.cfg.ext.max:
                chg_ok = False

            if c.voltage >= c.cfg.min:
                self.ctrl.req.send([self.cfg.bms,"rly", st=False])
                logger.error(f"Cell {c} overvoltage, turned off")

            if c.voltage <= c.cfg.ext.max:
                dis_ok = False

            if c.voltage <= c.cfg.min:
                self.ctrl.req.send([self.cfg.bms,"rly", st=False])
                logger.error(f"Cell {c} undervoltage, turned off")

        if self.chg_set != chg_ok or self.dis_set != dis_ok:
            # send limits to BMS in mplex
            await self.ctrl.req.send(["local",self.cfg.bms,"cell"], okch=chg_ok, okdis=dis_ok)
            self.chg_set = chg_ok
            self.dis_set = dis_ok




    async def task_temperature(self):
        """
        Periodically check the cell temperatures
        """
        while True:
            hdr,res = await self.send(RequestCellTemperature())
            chg = False
            for c,r in zip(self.cells,res):
                chg = r.to_cell(c) or chg
            if chg:
                await self.TemperatureChanged()

            await anyio.sleep(cfg.t.temperature)


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

    @dbus.signal()
    async def VoltageChanged(self) -> 'a(db)':
        """
        Return voltage plus in-bypass flag
        """
        return [(c.voltage,c.in_bypass) for c in self.cells]

    @dbus.signal()
    async def TemperatureChanged(self) -> 'a(dd)':
        """
        Return current temperatures (int,ext)
        """
        return [(c.internal_temp,c.external_temp) for c in self.cells]

    @dbus.method
    async def GetNCells(self) -> 'y':
        """
        Number of cells in this battery
        """
        return len(self.cells)

    @dbus.method
    async def GetName(self) -> 's':
        """
        Number of cells in this battery
        """
        return self.name

