import errno

import machine
import uos
import usys

from moat.micro.cmd import BaseCmd
from moat.micro.compat import TaskGroup, sleep_ms, ticks_diff, ticks_ms
from moat.micro.proto.stack import SilentRemoteError as FSError


class Cmd(BaseCmd):
    _bus_cache = None  # c,d > busobj

    def __init__(self, parent, name, cfg, gcfg):
        super().__init__(parent)
        self._bus_cache = dict()
        self.cfg = cfg

    def _bus(self, cd, drop=False):
        # (c,d) > bus
        c, d = cd
        cd = (c, d)
        if drop:
            return self._bus_cache.pop(cd)
        else:
            return self._bus_cache[cd]

    def _del_cd(self, cd):
        bus = self._bus(cd, True)
        # bus.close()

    def cmd_reset(self, p=None):
        # close all
        for b in self._bus_cache.values():
            pass  # b.close()
        self._bus_cache = dict()

    def cmd_open(self, c, d, cx={}, dx={}, f=1000000, t=1000000, s=False):
        cd = (c, d)
        if cd in self._bus_cache:
            pass  # close it
        c = machine.Pin(c, **cx)
        d = machine.Pin(d, **cx)
        bus = (machine.SoftI2C if s else machine.I2C)(scl=c, sda=d, freq=f, timeout=t)
        self._bus_cache[cd] = bus
        return cd

    def cmd_rd(self, cd, i, n=16):
        # read bus
        bus = self._bus(cd)
        return bus.readfrom(i, n)

    def cmd_wr(self, cd, i, buf):
        # write bus
        bus = self._bus(cd)
        return bus.writeto(i, buf)

    def cmd_wrrd(self, cd, i, buf, n=16):
        # write-then-read
        bus = self._bus(cd)
        d = bus.writeto(i, buf, False)
        if d < len(buf):
            return -d
        return bus.readfrom(i, n)

    def cmd_cl(self, cd):
        # close
        self._del_cd(cd)

    def cmd_scan(self, cd):
        # dir
        bus = self._bus(cd)
        return bus.scan()
