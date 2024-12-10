
from moat.cmd import BaseCmd
from moat.compat import wait_for_ms, Event, TimeoutError, Lock
import machine as M
from serialpacker import SerialPacker
from moat.proto.stream import AsyncStream

# Serial packet forwarder
# cfg:
# uart: N
# tx: PIN
# rx: PIN
# baud: 9600
# max:
#   len: N
#   idle: MSEC
# start: NUM
# 
class Serial:
    max_idle = 100

    def __init__(self, cmd, cfg, gcfg):
        self.cmd = cmd
        self.cfg = cfg
        self.xmit_evt = Event()
        self.w_lock = Lock()

    async def run(self):
        cfg = self.cfg
        self.ser = AsyncStream(M.UART(cfg.get("uart",0),tx=M.Pin(cfg.get("tx",0)),rx=M.Pin(cfg.get("rx",1)),baudrate=cfg.get("baud",9600)))
        sp = {}
        try:
            sp["max_idle"] = self.max_idle = cfg["max"]["idle"]
        except KeyError:
            sp["max_idle"] = self.max_idle
        try:
            sp["max_packet"] = cfg["max"]["len"]
        except KeyError:
            pass
        try:
            sp["frame_start"] = cfg["start"]
        except KeyError:
            pass
        try:
            sp["mark"] = cfg["mark"]
        except KeyError:
            pass
        self.pack = SerialPacker(**sp)

        buf = bytearray(32)
        cons = bytearray()
        timeout = None
        while True:
            if timeout is None:
                n = await self.ser.readinto(buf)
                if not n:
                    continue
                timeout = self.max_idle
            else:
                try:
                    n = await wait_for_ms(timeout, self.ser.readinto, buf)
                except TimeoutError:
                    if cons:
                        await self.cmd.send_raw(cons)
                        cons = bytearray()
                    timeout = None
                    continue

            for i in range(n):
                p = self.pack.feed(buf[i])
                if p is None:
                    continue
                if isinstance(p,int):  # console byte
                    cons.append(p)
                    if len(cons) > 127 or p == 10:  # linefeed
                        await self.cmd.send_raw(cons)
                        cons = bytearray()
                else:  # "real" message
                    await self.cmd.send_pkt(p)

    async def send(self, data):
        h,data,t = self.pack.frame(data)
        async with self.w_lock:
            await self.ser.write(h)
            await self.ser.write(data)
            await self.ser.write(t)

    async def send_raw(self, data):
        async with self.w_lock:
            await self.ser.write(data)

    async def err_count(self):
        try:
            return {
                "crc":self.pack.err_crc,
                "frame":self.pack.err_frame,
            }
        finally:
            self.pack.err_crc = 0
            self.pack.err_frame = 0


class SerialCmd(BaseCmd):
    def __init__(self, parent, name, cfg, gcfg):
        super().__init__(parent)
        self.ser = Serial(self, cfg, gcfg)
        self.name = name

    async def run(self):
        try:
            await self.ser.run()
        finally:
            del self.ser

    async def cmd_errcount(self):
        return self.ser.err_count()

    async def cmd_send(self, data, raw=False):
        if raw:
            await self.ser.send_raw(data)
        else:
            await self.ser.send(data)

    async def send_raw(self, data):
        await self.request.send_nr([self.name, "in_raw"], data)

    async def send_pkt(self, data):
        await self.request.send_nr([self.name, "in_pkt"], data)

