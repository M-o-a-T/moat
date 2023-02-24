import machine

from .cmd import BaseCmd
from .compat import TaskGroup, sleep_ms, ticks_ms, ticks_diff
from .proto import RemoteError
from .proto.stream import drop_proxy
from ..util import merge

import uos
import usys
import gc

class SysCmd(BaseCmd):
    # system and other low level stuff
    def __init__(self, parent):
        super().__init__(parent)
        self.repeats = {}

    async def cmd_is_up(self):
        await self.request.send_nr("link",True)

    async def cmd_state(self, state=None):
        # set/return the MoaT state file contents
        if state is not None:
            f=open("moat.state","w")
            f.write(state)
            f.close()
        else:
            try:
                f=open("moat.state","r")
            except OSError:
                state=None
            else:
                state = f.read()
                f.close()
        return dict(n=state, c=self.base.moat_state, fb=self.base.is_fallback)

    async def cmd_test(self):
        # return a simple test string
        return b"a\x0db\x0ac"

    async def cmd_cfg(self, cfg=None, mode=0):
        # mode 0: update current config
        # mode 1: update current config, write moat.cfg
        # mode 2: update moat.cfg
        # mode 3: update moat_fb.cfg
        #
        # If cfg is None, return current/stored/fallback config (mode=0/2/3),
        # else if cfg is None and mode is 1, write running config to storage,
        # else if cfg.port exists, replace config,
        # else merge config.

        import msgpack
        if mode > 1:
            try:
                f=open("/moat_fb.cfg" if mode == 3 else "/moat.cfg","rb")
            except FileNotFoundError:
                cur = {}
            else:
                with f:
                    cur = msgpack.unpackb(f.read())
        else:
            cur = self.base.cfg

        if cfg is None and mode != 1:
            return cur

        if mode > 1 and "port" in cfg:
            cur = cfg  # just to avoid redundant work
        elif cfg:
            merge(cur, cfg, drop=("port" in cfg))

        if mode > 0:
            cur = msgpack.packb(cur)
            f=open("/moat_fb.cfg" if mode == 3 else "/moat.cfg","wb")
            with f:
                f.write(cur)
        if mode < 2 and cfg is not None:
            await self.base.config_updated()
            await self.request.send_nr(["mplex","cfg"], cfg=cfg)

    async def cmd_eval(self, val, attrs=()):
        # possibly evaluates the string
        if isinstance(val,str):
            val = eval(val,dict(s=self.parent))
        # otherwise it's probably a proxy
        for vv in attrs:
            try:
                val = getattr(v,vv)
            except AttributeError:
                val = val[vv]
        return (val,repr(val))  # may send a proxy

    async def cmd_unproxy(self, p):
        # tell the client to forget about a proxy
        # NOTE pass the proxy's name, not the proxy object!
        if p == "" or p == "-" or p[0] == "_":
            raise RuntimeError("cannot be deleted")
        drop_proxy(p)

    async def cmd_dump(self, x):
        # evaluates the string
        # warning: may need a heap of memory
        res = eval(x,dict(s=self.parent))
        d = {}
        for k in dir(res):
            d[k] = repr(getattr(res,k))
        return d

    async def cmd_info(self):
        # return some basic system info
        d = {}
        fb = self.base.is_fallback
        if fb is not None:
            d["fallback"] = fb
        d["path"] = usys.path
        return d

    async def cmd_mem(self):
        # info about memory
        t1 = ticks_ms()
        f1 = gc.mem_free()
        gc.collect()
        f2 = gc.mem_free()
        t2 = ticks_ms()
        return dict(t=ticks_diff(t2,t1), f=f2, c=f2-f1)


    async def cmd_boot(self, code):
        if code != "SysBooT":
            raise RuntimeError("wrong")

        async def _boot():
            await sleep_ms(100)
            await self.request.send_nr("link",False)
            await sleep_ms(100)
            machine.soft_reset()
        await self.request._tg.spawn(_boot)
        return True

    async def cmd_reset(self, code):
        if code != "SysRsT":
            raise RuntimeError("wrong")
        async def _boot():
            await sleep_ms(100)
            await self.request.send_nr("link",False)
            await sleep_ms(100)
            machine.reset()
        await self.request._tg.spawn(_boot)
        return True

    async def cmd_stop(self, code):
        # terminate the MoaT stack w/o rebooting
        if code != "SysStoP":
            raise RuntimeError("wrong")
        async def _boot():
            await sleep_ms(100)
            await self.request.send_nr("link",False)
            await sleep_ms(100)
            raise SystemExit
        await self.request._tg.spawn(_boot)
        return True


    async def cmd_machid(self):
        # return the machine's unique ID
        return machine.unique_id()

    async def cmd_rtc(self, d=None):
        if d is None:
            return machine.RTC.now()
        else:
            machine.RTC((d[0],d[1],d[2],0, d[3],d[4],d[5],0))

    async def cmd_pin(self, n, v=None, **kw):
        p=machine.Pin(n, **kw)
        if v is not None:
            p.value(v)
        return p.value()
        
    async def cmd_adc(self, n):
        p=machine.ADC(n)
        return p.read_u16()  # XXX this is probably doing a sync wait

    async def run(self):
        await self.request.send_nr("link",True)

class StdBase(BaseCmd):
    #Standard toplevel base implementation

    def __init__(self, parent, fallback=None, state=None, cfg={}, **k):
        super().__init__(parent, **k)

        self.is_fallback=fallback
        self.moat_state=state
        self.cfg = cfg

        self.dis_sys = SysCmd(self)

    async def cmd_ping(self, m=None):
        print("PLING",m)
        return "R:"+str(m)

