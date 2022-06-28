import machine

from .cmd import BaseCmd
from moat.compat import TaskGroup, sleep_ms


class SysCmd(BaseCmd):
    # system and other low level stuff
    async def later(self, delay, p,*a,**k):
        async def _later(d,p,a,k):
            await sleep_ms(d)
            await p(*a,**k)
        await self.request._tg.spawn(_later,delay,p,a,k)

    async def cmd_boot(self, code):
        if code != "SysBooT":
            raise RuntimeError("wrong")

        async def _boot(self):
            machine.soft_reset()
        await self.later(100,_boot)
        return True

    async def cmd_repl(self, code):
        # boots to REPL
        if code != "SysRepL":
            raise RuntimeError("wrong")

        f = open("/moat_skip","w")
        f.close()

        async def _boot(self):
            machine.soft_reset()
        await self.later(100,_boot)
        return True

    async def cmd_reset(self, code):
        if code != "SysRsT":
            raise RuntimeError("wrong")
        async def _boot(self):
            machine.reset()
        await self.later(100,_boot)
        return True

    async def cmd_machid(self):
        return machine.unique_id

    async def cmd_pin(self, n, v=None, **kw):
        p=machine.Pin(n, **kw)
        if v is not None:
            p.value(v)
        return p.value()
        
    async def cmd_adc(self, n):
        p=machine.ADC(n)
        return p.read_u16()  # XXX this is probably doing a sync wait


class FsCmd(BaseCmd):
    pass


class StdBase(BaseCmd):
    #Standard toplevel base implementation

    def __init__(self, parent, **k):
        super().__init__(parent, **k)

        self.dis_sys = SysCmd(self)
        self.dis_f = FsCmd(self)

    async def cmd_ping(self, m=None):
        print("PLING",m)
        return "R:"+str(m)

