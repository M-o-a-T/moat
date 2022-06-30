import machine

from .cmd import BaseCmd
from moat.compat import TaskGroup, sleep_ms, ticks_ms, ticks_diff

import uos
import usys
import gc

class SysCmd(BaseCmd):
    # system and other low level stuff
    async def later(self, delay, p,*a,**k):
        async def _later(d,p,a,k):
            await sleep_ms(d)
            try:
                await p(*a,**k)
            except Exception:
                print(getattr(p,'__name__',p), a,k)
                raise
        await self.request._tg.spawn(_later,delay,p,a,k)

    async def cmd_state(self, state=None):
        # set/return the MoaT state file contents
        if state is None:
            try:
                f=open("moat.status","r")
            except OSError:
                return "skip"
            else:
                res = f.read()
                f.close()
                return res
        else:
            f=open("moat.status","w")
            f.write(state)
            f.close()

    async def cmd_test(self):
        # return a simple test string
        return b"a\x0db\x0ac"

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
            machine.soft_reset()
        await self.later(100,_boot)
        return True

    async def cmd_repl(self, code):
        # boots to REPL
        if code != "SysRepL":
            raise RuntimeError("wrong")

        f = open("/moat_skip","w")
        f.close()

        async def _boot():
            machine.soft_reset()
        await self.later(100,_boot)
        return True

    async def cmd_reset(self, code):
        if code != "SysRsT":
            raise RuntimeError("wrong")
        async def _boot():
            machine.reset()
        await self.later(100,_boot)
        return True

    async def cmd_stop(self, code):
        # terminate the MoaT stack w/o rebooting
        if code != "SysStoP":
            raise RuntimeError("wrong")
        async def _boot():
            raise SystemExit
        await self.later(100,_boot)
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


class FsCmd(BaseCmd):
    listen_s = None
    client = None
    clients = None  # type: set[UFuseClient]
    wdt = None
    wdt_any = False
    subs = {} # nr > (cb,topic)
    sub_nr = 1

    _fd_last = 0
    _fd_cache = None
    _repl_nr = -1
    debug_console = False

    def __init__(self, parent):
        super().__init__(parent)
        self._fd_cache = dict()

    _fs_prefix = ""
    def _fsp(self, p):
        if self._fs_prefix:
            p=self._fs_prefix+"/"+p
        if p == "":
            p = "/"
#       elif p == ".." or p.startswith("../") or "/../" in p: or p.endswith("/..")
#           raise RemoteError("nf")
        return p

    def _fd(self, fd, drop=False):
        # filenr > fileobj
        if drop:
            return self._fd_cache.pop(fd)
        else:
            return self._fd_cache[fd]

    def _add_f(self, f):
        # fileobj > filenr
        self._fd_last += 1
        fd = self._fd_last
        self._fd_cache[fd] = f
        return fd

    def _del_f(self,fd):
        f = self._fd_cache.pop(fd)
        f.close()

    def cmd_reset(self, p=None):
        # close all
        for v in self._fd_cache.values():
            v.close()
        self._fd_cache = dict()

        if not p or p == "/":
            self._fs_prefix = ""
        elif p[0] == "/":
            self._fs_prefix = p
        else:
            self._fs_prefix += "/"+p

    def cmd_open(self, p, m="r"):
        try:
            f=open(p,m+'b')
        except OSError as e:
            if e.errno == errno.ENOENT:
                raise RemoteError("fn")
            raise
        else:
            return self._add_f(f)

    def cmd_rd(self, fd, off=0, n=64):
        # read
        f = self._fd(fd)
        f.seek(off)
        return f.read(n)

    def cmd_wr(self, fd, data, off=0):
        # write
        f = self._fd(fd)
        f.seek(off)
        return f.write(data)


    def cmd_cl(self, fd):
        # close
        self._del_f(fd)

    def cmd_dir(self, p="", x=False):
        # dir
        p = self._fsp(p)
        if x:
            try:
                 uos.listdir(p)
            except AttributeError:
                return [ dict(n=x[0],t=x[1],s=x[3]) for x in uos.ilistdir(p) ]
        else:
            try:
                return uos.listdir(p)
            except AttributeError:
                return [ x[0] for x in uos.ilistdir(p) ]

    def cmd_mkdir(self, p):
        # new dir
        p = self._fsp(p)
        uos.mkdir(p)


    def cmd_hash(self, p):
        # Hash the contents of a file
        import uhashlib
        _h = uhashlib.sha256()
        _mem = memoryview(bytearray(512))

        p = self._fsp(p)
        with open(p, "rb") as _f:
            while True:
                n = _f.readinto(_mem)
                if not n: break
                _h.update(_mem[:n])
        return _h.digest()
        

    def cmd_stat(self, p):
        p = self._fsp(p)
        try:
            s = uos.stat(p)
        except OSError as e:
            if e.errno == errno.ENOENT:
                raise RemoteError("fn")
            raise
        if s[0] & 0x8000: # file
            return dict(m="f",s=s[6], t=s[7], d=s)
        elif s[0] & 0x4000: # file
            return dict(m="d", t=s[7], d=s)
        else:
            return dict(m="?", d=s)

    def cmd_mv(self, s,d, x=None):
        # move file
        p = self._fsp(s)
        q = self._fsp(d)
        uos.stat(p)  # must exist
        if msg.get("n", False):
            # dest must not exist
            try:
                uos.stat(q)
            except OSError as err:
                if err.errno != errno.ENOENT:
                    raise
            else:
                raise RemoteError("fx")
        if x is None:
            uos.rename(p,q)
        else:
            r = self._fsp(x)
            # exchange contents, via third file
            try:
                uos.stat(r)
            except OSError as err:
                if err.errno != errno.ENOENT:
                    raise
            else:
                raise RemoteError("fx")
            uos.rename(p,r)
            uos.rename(q,p)
            uos.rename(r,q)

    def cmd_rm(self, p):
        # unlink
        try:
            uos.remove(p)
        except OSError as e:
            if e.errno == errno.ENOENT:
                raise RemoteError("fn")
            raise

    def cmd_rmdir(self, p):
        # unlink dir
        try:
            uos.rmdir(p)
        except OSError as e:
            if e.errno == errno.ENOENT:
                raise RemoteError("fn")
            raise

    def cmd_new(self, p):
        # new file
        f = open(p,"wb")
        f.close()


class StdBase(BaseCmd):
    #Standard toplevel base implementation

    def __init__(self, parent, fallback=None, **k):
        super().__init__(parent, **k)

        self.is_fallback=fallback

        self.dis_sys = SysCmd(self)
        self.dis_f = FsCmd(self)

    async def cmd_ping(self, m=None):
        print("PLING",m)
        return "R:"+str(m)

