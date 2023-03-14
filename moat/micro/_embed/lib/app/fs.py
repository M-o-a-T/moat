import machine

from moat.micro.cmd import BaseCmd
from moat.micro.compat import TaskGroup, sleep_ms, ticks_ms, ticks_diff
from moat.micro.proto.stack import SilentRemoteError as FSError

import uos
import usys
import errno

class FsCmd(BaseCmd):
    _fd_last = 0
    _fd_cache = None

    def __init__(self, parent, name, cfg, gcfg):
        super().__init__(parent)
        self._fd_cache = dict()
        self.cfg = cfg
        try:
            self._pre = cfg["prefix"]
            if self._pre and self._pre[-1] != "/":
                self._pre += "/"
        except KeyError:
            self._pre = ""

    def _fsp(self, p):
        if self._pre:
            p=self._pre+p
        if p == "":
            p = "/"
#       elif p == ".." or p.startswith("../") or "/../" in p: or p.endswith("/..")
#           raise FSError("nf")
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
                raise FSError("fn")
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
                raise FSError("fn")
            raise
        if s[0] & 0x8000: # file
            return dict(m="f",s=s[6], t=s[7], d=s)
        elif s[0] & 0x4000: # file
            return dict(m="d", t=s[7], d=s)
        else:
            return dict(m="?", d=s)

    def cmd_mv(self, s,d, x=None, n=False):
        # move file
        p = self._fsp(s)
        q = self._fsp(d)
        uos.stat(p)  # must exist
        if n:
            # dest must not exist
            try:
                uos.stat(q)
            except OSError as err:
                if err.errno != errno.ENOENT:
                    raise
            else:
                raise FSError("fx")
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
                raise FSError("fx")
            uos.rename(p,r)
            uos.rename(q,p)
            uos.rename(r,q)

    def cmd_rm(self, p):
        # unlink
        try:
            uos.remove(p)
        except OSError as e:
            if e.errno == errno.ENOENT:
                raise FSError("fn")
            raise

    def cmd_rmdir(self, p):
        # unlink dir
        try:
            uos.rmdir(p)
        except OSError as e:
            if e.errno == errno.ENOENT:
                raise FSError("fn")
            raise

    def cmd_new(self, p):
        # new file
        f = open(p,"wb")
        f.close()

