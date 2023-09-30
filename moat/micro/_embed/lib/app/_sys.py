import gc

import machine
import sys
from moat.util import NotGiven, drop_proxy

from moat.micro.cmd.base import BaseCmd
from moat.micro.compat import TaskGroup, sleep_ms, ticks_diff, ticks_ms


class SysCmd(BaseCmd):
    # system and other low level stuff
    def __init__(self, parent):
        super().__init__(parent)
        self.repeats = {}

    async def cmd_state(self, state=None):
        """
        Set/return the string in the MoaT state file.

        The result is a dict:
        * n: current file content
        * c: state when the system was booted
        * fb: flag whether the current state is a fall-back state
        """
        if state is not None:
            f = open("moat.state", "w")
            f.write(state)
            f.close()
        else:
            try:
                f = open("moat.state", "r")
            except OSError:
                state = None
            else:
                state = f.read()
                f.close()
        return dict(n=state, c=self.root.moat_state, fb=self.root.is_fallback)

    async def cmd_test(self):
        """
        Returns a test string: r CR n LF - NUL c ^C e ESC !

        Use this to verify that nothing mangles anything.
        """
        return b"r\x0dn\x0a-\x00x\x0ce\x1b!"

    async def cmd_unproxy(self, p):
        """
        Tell the client to forget about a proxy.

        @p accepts either the proxy's name, or the proxied object.
        """
        if p == "" or p == "-" or p[0] == "_":
            raise RuntimeError("cannot be deleted")
        drop_proxy(p)

    async def cmd_eval(self, x, p=(), r=False):
        """
        Evaluate an object @x, returns a partial view of its attributes;
        the return format is identical to that of `cmd_cfg_r`; set @p
        to access a sub-object.

        if p is `None`
        """
        if isinstance(x, str):
            x = eval(x, dict(s=self.parent))

        if not isinstance(x, (int, float, list, tuple, dict)):
            try:
                obj2name(x)
            except KeyError:
                try:
                    obj2name(type(x))
                except KeyError:
                    x = self._cmd_part(x.__dict__, p)
        if r:
            return repr(x)
        return x

    async def cmd_info(self):
        """
        Returns some basic system info.
        """
        d = {}
        fb = self.root.is_fallback
        if fb is not None:
            d["fallback"] = fb
        d["path"] = sys.path
        return d

    async def cmd_mem(self):
        """
        Info about memory. Calls `gc.collect`.

        * f: free memory
        * c: memory freed by the garbage collector
        * t: time (ms) for the garbage collector to run
        """
        t1 = ticks_ms()
        f1 = gc.mem_free()
        gc.collect()
        f2 = gc.mem_free()
        t2 = ticks_ms()
        return dict(t=ticks_diff(t2, t1), f=f2, c=f2 - f1)

    async def cmd_boot(self, code):
        """
        Reboot the system (soft reset).

        @code needs to be "SysBooT".
        """
        if code != "SysBooT":
            raise RuntimeError("wrong")

        async def _boot():
            await sleep_ms(100)
            await self.root.send_nr("link", False)
            await sleep_ms(1000)
            machine.soft_reset()

        await self.root.spawn(_boot, _name="_sys.boot1")
        return True

    async def cmd_reset(self, code):
        """
        Reboot the system (hard reset).

        @code needs to be "SysRsT".
        """
        if code != "SysRsT":
            raise RuntimeError("wrong")

        async def _boot():
            await sleep_ms(100)
            await self.root.send_nr("link", False)
            await sleep_ms(100)
            machine.reset()

        await self.root.spawn(_boot, _name="_sys.boot2")
        return True

    async def cmd_stop(self, code):
        """
        Terminate MoaT and go back to MicroPython.

        @code needs to be "SysStoP".
        """
        # terminate the MoaT stack w/o rebooting
        if code != "SysStoP":
            raise RuntimeError("wrong")

        async def _boot():
            await sleep_ms(100)
            await self.request.send_nr("link", False)
            await sleep_ms(100)
            raise SystemExit

        await self.request._tg.spawn(_boot, _name="_sys.boot3")
        return True

    async def cmd_load(self, n, m, r=False, kw={}):
        """
        (re)load a dispatcher: set dis_@n to point to @m.

        Set @r if you want to reload the module if it already exists.
        @kw may contain additional params for the module.

        For example, ``most micro cmd sys.load -v n f -v m fs.FsCmd``
        loads the file system module if it isn't loaded already.
        """
        om = getattr(self.parent, "dis_" + n, None)
        if om is not None:
            if not r:
                return
            await om.aclose()
            del om  # free memory

        from .main import import_app

        m = import_app(m, drop=True)
        m = m(self.parent, n, kw, self.root.cfg)
        setattr(self.parent, "dis_" + n, m)
        await self.parent._tg.spawn(m._run_sub, _name="_sys.load")

    async def cmd_machid(self):
        """
        Return the machine's unique ID. This is the bytearray returned by
        `micropython.unique_id`.
        """
        return machine.unique_id()

    async def cmd_rtc(self, d=None):
        """
        Set, or query, the current time.
        """
        if d is None:
            return machine.RTC.now()
        else:
            machine.RTC((d[0], d[1], d[2], 0, d[3], d[4], d[5], 0))

    async def cmd_pin(self, n, v=None, **kw):
        """
        Set or read a digital pin.
        """
        p = machine.Pin(n, **kw)
        if v is not None:
            p.value(v)
        return p.value()

    async def cmd_adc(self, n):
        """
        Read an analog pin.
        """
        p = machine.ADC(n)
        return p.read_u16()  # XXX this is probably doing a sync wait

    async def run(self):
        await self.root.wait_ready()
        await self.root.send_nr("link", True)


    async def cmd_ping(self, m=None):
        """
        Echo @m.

        This is for humans. Don't use it for automated keepalive.
        """
        return {"m": m, "rep": repr(m)}
