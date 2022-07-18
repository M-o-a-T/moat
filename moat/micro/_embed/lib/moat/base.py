import machine

from .cmd import BaseCmd
from .compat import TaskGroup, sleep_ms, ticks_ms, ticks_diff
from .proto import RemoteError

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

    async def cmd_cfg(self, cfg=None, fallback=None):
        import msgpack
        if cfg is None:
            if fallback is None:
                return self.base.cfg
            else:
                f=open("/moat_fb.cfg" if fallback else "/moat.cfg","wb")
                cfg = msgpack.unpackb(f.read())
                f.close()
                return cfg

        cfg = msgpack.packb(cfg)
        f=open("/moat_fb.cfg" if fallback else "/moat.cfg","wb")
        f.write(cfg)
        f.close()
        # cfg is re-read on restart; TODO maybe interactive update
        # await self.base.cfg_updated()

    async def cmd_eval(self, x):
        # evaluates the string
        return eval(x,dict(s=self.parent))

    async def cmd_dump(self, x):
        # evaluates the string
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
        return machine.unique_id

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

