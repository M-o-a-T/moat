
from moat.cmd import BaseCmd
from moat.compat import wait_for, Event, TimeoutError, Lock
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

	def __init__(self, cfg, gcfg):
		self.cfg = cfg
		self.xmit_evt = Event()

	async def run(self):
        self.ser = AsyncStream(M.UART(cfg.get("uart",0),tx=m.Pin(cfg.get("tx",0)),rx=m.Pin(cfg.get("rx",1)),baudrate=cfg.get("rate",9600)))
        sp = {}
        try:
            sp["max_idle"] = self.max_idle = cfg.max.idle
        except AttributeError:
            sp["max_idle"] = self.max_idle
        try:
            sp["max_packet"] = cfg.max.len
        except AttributeError:
            pass
        try:
            sp["frame_start"] = cfg.start
        except AttributeError:
            pass
        self.pack = SerialPacker(**sp)

        buf = bytes(32)
        timeout = None
		while True:
            if timeout is None:
                n = await self.ser.readinto(buf)
                if not n:
                    continue
                timeout = self.max_idle
            else:
                try:
                    n = await wait_for(timeout, self.ser.readinto(buf))
                except TimeoutError:
                    r = self.pack.read()
                    if r:
                        await self.cmd.send_raw(r)
                    timeout = None
                    continue

            for i in range(n):
                 p = self.pack.feed(buf[i])
                 if p is not None:
                     await self.cmd.send_pkt(p)
            
    async def send(self, data):
        h,t = self.pack.frame(data)
        async with self.w_lock:
            await self.write(h)
            await self.write(data)
            await self.write(t)

    async def send_raw(self, data):
        async with self.w_lock:
            await self.write(data)

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
	def __init__(self, parent, ser, name):
		super().__init__(parent)
		self.ser = ser
		self.name = name
        ser.cmd = self

    async def cmd_errcount(self):
        return self.ser.err_count()

	async def cmd_send(self, data, raw=False):
        if raw:
            await self.ser.send_raw(data)
        else:
            await self.ser.send(data)

    async def send_raw(self, data):
        await self.request.send_nr([self.name, "raw"], data)

    async def send_pkt(self, data):
        await self.request.send_nr([self.name, "pkt"], data)

