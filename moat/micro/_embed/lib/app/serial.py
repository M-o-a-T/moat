import machine as M
from serialpacker import SerialPacker

from moat.micro.cmd import BaseCmd
from moat.micro.compat import Event, Lock, TimeoutError, wait_for_ms
from moat.micro.proto.stream import AsyncStream


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
    pack = None

    def __init__(self, cmd, cfg, gcfg):
        self.cmd = cmd
        self.cfg = cfg
        self.xmit_evt = Event()
        self.w_lock = Lock()

    async def run(self, cmd):
        cfg = self.cfg
        uart_cfg = {}
        if 'tx' in cfg:
            uart_cfg['tx'] = M.pin(cfg["tx"])
        if 'rx' in cfg:
            uart_cfg['rx'] = M.pin(cfg["rx"])
        uart_cfg['baudrate']=cfg.get("rate", 9600)

        self.ser = AsyncStream(
            M.UART(cfg.get("uart", 0), **uart_cfg)
        )
        sp_cfg = cfg.get('frame', None)
        if sp_cfg is not None:
            sp = {}
            try:
                sp["max_idle"] = self.max_idle = sp_cfg["idle"]
            except KeyError:
                sp["max_idle"] = self.max_idle
            try:
                sp["max_packet"] = sp_cfg["len"]
            except KeyError:
                pass
            try:
                sp["frame_start"] = sp_cfg["start"]
            except KeyError:
                pass
            try:
                sp["mark"] = sp_cfg["mark"]
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
                if self.pack is not None:
                    p = self.pack.feed(buf[i])
                    if p is None:
                        continue
                    if not isinstance(p, int):  # console byte
                        await self.cmd.send_pkt(p)
                        continue
                cons.append(p)
                if len(cons) > 127 or p == 10:  # linefeed
                    await self.cmd.send_raw(cons)
                    cons = bytearray()

    async def send(self, data):
        h, data, t = self.pack.frame(data)
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
                "crc": self.pack.err_crc,
                "frame": self.pack.err_frame,
            }
        finally:
            self.pack.err_crc = 0
            self.pack.err_frame = 0


class SerialCmd(BaseCmd):
    def __init__(self, parent, name, cfg, gcfg):
        super().__init__(parent)
        self.ser = Serial(self, cfg, gcfg)
        self.name = name
        self.dp = self.cfg.get("dest", None)
        self.dr = self.cfg.get("dest_raw", None)

    async def run(self):
        try:
            await self.ser.run(self)
        finally:
            del self.ser

    async def cmd_errcount(self):
        return self.ser.err_count()

    async def cmd_send(self, data, raw=False):
        if raw:
            await self.ser.send_raw(data)
        else:
            await self.ser.send(data)

    def cmd_x(self, data):
        return self.cmd_send(data, raw=False)

    def cmd_w(self, data):
        return self.cmd_send(data, raw=True)

    async def send_raw(self, data):
        if self.dr is not None:
            return await self.root.send_nr(self.dr, data)
        # TODO store for eventual reading by the remote end


    async def send_pkt(self, data):
        if self.dp is not None:
            return await self.root.send_nr(self.dp, data)
        # TODO store for eventual reading by the remote end
