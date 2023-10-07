import machine as M

from moat.micro.proto.stream import FileBuf
from moat.micro.compat import AC_use, TimeoutError


# Serial link driver
# cfg:
# uart: N
# tx: PIN
# rx: PIN
# baud: 9600
#
class Serial(FileBuf):
    max_idle = 100
    pack = None

    def __init__(self, cfg):
        self.cfg = cfg

    async def stream(self):
        cfg = self.cfg
        uart_cfg = {}
        if 'tx' in cfg:
            uart_cfg['tx'] = M.pin(cfg["tx"])
        if 'rx' in cfg:
            uart_cfg['rx'] = M.pin(cfg["rx"])
        if 'rts' in cfg:
            uart_cfg['rts'] = M.pin(cfg["rts"])
        if 'cts' in cfg:
            uart_cfg['cts'] = M.pin(cfg["cts"])
        uart_cfg['txbuf'] = cfg.get("txb",128)
        uart_cfg['rxbuf'] = cfg.get("rxb",128)

        p = cfg.get("mode", {})
        uart_cfg['baudrate'] = p.get("rate", 9600)
        uart_cfg['parity'] = p.get("parity", None)
        uart_cfg['bits'] = p.get("bits", 8)
        fl =  p.get("flow", "")
        f = 0
        if "C" in fl:
            f |= UART.CTS
        if "R" in fl:
            f |= UART.RTS
        uart_cfg['stop'] = p.get("stop", None) or 1  # no 1.5 stop bits

        ser = M.UART(cfg.get("port", 0), **uart_cfg)
        await AC_use(self, ser.deinit)
        if (t := cfg.get("flush")):
            if t is True:
                t = 200
            while True:
                buf = bytearray(32)
                try:
                    n = await wait_for_ms(t,ser.rd,buf)
                except TimeoutError:
                    break
                else:
                    log("Flush: %r", buf[:n])

        return ser
