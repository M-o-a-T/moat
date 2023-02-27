import machine

from .cmd import BaseCmd
from .compat import TaskGroup, sleep_ms, ticks_ms, ticks_diff
from .proto import RemoteError
from .proto.stream import drop_proxy

import uos
import usys
import gc

class SysCmd(BaseCmd):
    # system and other low level stuff
    def __init__(self, parent):
        super().__init__(parent)
        self.repeats = {}

    async def cmd_is_up(self):
        """
        Trigger an unsolicited ``link`` message. The data will be ``True``
        obviously.
        """
        await self.request.send_nr("link",True)

    async def cmd_state(self, state=None):
        """
        Set/return the string in the MoaT state file.

        The result is a dict:
        * n: current file content
        * c: state when the system was booted
        * fb: flag whether the current state is a fall-back state
        """
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
        """
        Returns a test string: r CR n LF - NUL c ^C e ESC !

        Use this to verify that nothing mangles anything.
        """
        return b"r\x0dn\x0a-\x00x\x0ce\x1b!"

    async def cmd_cfg(self, cfg=None, mode=0):
        """
        Configuration file mangling.

        * mode: what to do

            0: update current config
            1: update current config, write moat.cfg
            2: update moat.cfg
            3: update moat_fb.cfg

        * cfg: items to update/set
            If ``hasattr(cfg,'port')``, the current config is replaced.
            Otherwise it is merged with whatever is in ``cfg``.
            (Use ``Proxy('-')`` to delete an entry.)
            
        If cfg is None, return current/stored/fallback config (mode=0/2/3),
        else if cfg is None and mode is 1, write running config to storage,
        else if cfg.port exists, replace config,
        else merge config.

        Warning: mode 1 and sending ``cfg``=``None`` will return the current config.
        This can cause an out-of-memory condition. incremental reading is
        TODO.
        """

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
        """
        Evaluates ``val`` if it's a string, accesses ``attrs``,
        then returns a ``val, repr(val)`` tuple.

        If you get a `Proxy` object as the result, you need to call
        ``sys.unproxy`` to clear it from the cache.
        """
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
        """
        Tell the client to forget about a proxy.

        @p accepts either the proxy's name, or the proxied object.
        """
        if p == "" or p == "-" or p[0] == "_":
            raise RuntimeError("cannot be deleted")
        drop_proxy(p)

    async def cmd_dump(self, x):
        """
        Evaluate an object, returns a repr() of all its attributes.

        Warning: this may need a heap of memory.
        """
        if isinstance(x,str):
            x = eval(x,dict(s=self.parent))
        d = {}
        for k in dir(x):
            d[k] = repr(getattr(res,k))
        return d

    async def cmd_info(self):
        """
        Returns some basic system info.
        """
        d = {}
        fb = self.base.is_fallback
        if fb is not None:
            d["fallback"] = fb
        d["path"] = usys.path
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
        return dict(t=ticks_diff(t2,t1), f=f2, c=f2-f1)

    async def cmd_boot(self, code):
        """
        Reboot the system (soft reset).

        @code needs to be "SysBooT".
        """
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
        """
        Reboot the system (hard reset).

        @code needs to be "SysRsT".
        """
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
        """
        Terminate MoaT and go back to MicroPython.

        @code needs to be "SysStoP".
        """
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

    async def cmd_load(self, n, m, r=False, kw={}):
        """
        (re)load a dispatcher: set dis_@n to point to @m.

        Set @r if you want to reload the module if it already exists.
        @kw may contain additional params for the module.

        For example, ``most micro cmd sys.load -v n f -v m fs.FsCmd``
        loads the file system module if it isn't loaded already.
        """
        om = getattr(self.parent,"dis_"+n, None)
        if om is not None:
            if not r:
                return
            await om.aclose()
            del om  # free memory

        from .main import import_app
        m = import_app(m, drop=True)
        m = m(self.parent, n, kw, self.base.cfg)
        setattr(self.parent,"dis_"+n, m)
        await self.parent._tg.spawn(m.run_sub)

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
            machine.RTC((d[0],d[1],d[2],0, d[3],d[4],d[5],0))

    async def cmd_pin(self, n, v=None, **kw):
        """
        Set or read a digital pin.
        """
        p=machine.Pin(n, **kw)
        if v is not None:
            p.value(v)
        return p.value()
        
    async def cmd_adc(self, n):
        """
        Read an analog pin.
        """
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
        """
        Echo @m.

        This is for humans. Don't use it for automated keepalive.
        """
        print("PLING",m)
        return "R:"+str(m)

