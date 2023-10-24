import errno
import os

from moat.util import as_proxy

from moat.micro.cmd.base import BaseCmd
from moat.micro.proto.stack import SilentRemoteError


class FileNotFoundError(SilentRemoteError):
    def __reduce__(self):
        return (FileNotFoundError, (self.args[0],), {})


class FileExistsError(SilentRemoteError):
    def __reduce__(self):
        return (FileExistsError, (self.args[0],), {})


as_proxy("_FnErr", FileNotFoundError)
as_proxy("_FxErr", FileExistsError)


class Cmd(BaseCmd):
    _fd_last = 0
    _fd_cache = None

    def __init__(self, cfg):
        super().__init__(cfg)
        self._fd_cache = dict()
        try:
            self._pre = cfg["root"]
        except KeyError:
            self._pre = ""
        else:
            if self._pre and self._pre[-1] != "/":
                self._pre += "/"

    def _fsp(self, p):
        if self._pre:
            p = self._pre + p
        if p == "":
            p = "/"
        # elif p == ".." or p.startswith("../") or "/../" in p: or p.endswith("/..")
        # raise FSError("nf")
        return p

    def _fd(self, fd):
        # filenr > fileobj
        f = self._fd_cache[fd]
        # log(f"{fd}:{repr(f)}")
        return f

    def _add_f(self, f):
        # fileobj > filenr
        self._fd_last += 1
        fd = self._fd_last
        self._fd_cache[fd] = f
        # log(f"{fd}={repr(f)}")
        return fd

    def _del_f(self, fd):
        f = self._fd_cache.pop(fd)
        # log(f"{fd}!{repr(f)}")
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
            self._fs_prefix += "/" + p

    def cmd_open(self, p, m="r"):
        p = self._fsp(p)
        try:
            f = open(p, m + 'b')
        except OSError as e:
            if e.errno == errno.ENOENT:
                raise FileNotFoundError(p)
            raise
        else:
            return self._add_f(f)

    def cmd_rd(self, f, o=0, n=64):
        # read
        fh = self._fd(f)
        fh.seek(o)
        return fh.read(n)

    def cmd_wr(self, f, d, o=0):
        # write
        fh = self._fd(f)
        fh.seek(o)
        return fh.write(d)

    def cmd_cl(self, f):
        # close
        self._del_f(f)

    def cmd_ls(self, p="", x=False):
        # dir
        p = self._fsp(p)
        if x:
            try:
                os.listdir(p)
            except AttributeError:
                return [dict(n=x[0], t=x[1], s=x[3]) for x in os.ilistdir(p)]
        else:
            try:
                return os.listdir(p)
            except AttributeError:
                return [x[0] for x in os.ilistdir(p)]

    def cmd_mkdir(self, p):
        # new dir
        p = self._fsp(p)
        os.mkdir(p)

    def cmd_hash(self, p):
        # Hash the contents of a file
        import uhashlib

        _h = uhashlib.sha256()
        _mem = memoryview(bytearray(512))

        p = self._fsp(p)
        with open(p, "rb") as _f:
            while True:
                n = _f.readinto(_mem)
                if not n:
                    break
                _h.update(_mem[:n])
        return _h.digest()

    def cmd_stat(self, p):
        p = self._fsp(p)
        try:
            s = os.stat(p)
        except OSError as e:
            if e.errno == errno.ENOENT:
                raise FileNotFoundError(p)
            raise
        if s[0] & 0x8000:  # file
            return dict(m="f", s=s[6], t=s[7], d=s)
        elif s[0] & 0x4000:  # file
            return dict(m="d", t=s[7], d=s)
        else:
            return dict(m="?", d=s)

    def cmd_mv(self, s, d, x=None, n=False):
        # move file
        p = self._fsp(s)
        q = self._fsp(d)
        os.stat(p)  # must exist
        if n:
            # dest must not exist
            try:
                os.stat(q)
            except OSError as err:
                if err.errno != errno.ENOENT:
                    raise
            else:
                raise FileExistsError(q)
        if x is None:
            os.rename(p, q)
        else:
            r = self._fsp(x)
            # exchange contents, via third file
            try:
                os.stat(r)
            except OSError as err:
                if err.errno != errno.ENOENT:
                    raise
            else:
                raise FileExistsError(r)
            os.rename(p, r)
            os.rename(q, p)
            os.rename(r, q)

    def cmd_rm(self, p):
        # unlink
        p = self._fsp(p)
        try:
            os.remove(p)
        except OSError as e:
            if e.errno == errno.ENOENT:
                raise FileNotFoundError(p)
            raise

    def cmd_rmdir(self, p):
        # unlink dir
        p = self._fsp(p)
        try:
            os.rmdir(p)
        except OSError as e:
            if e.errno == errno.ENOENT:
                raise FileNotFoundError(p)
            raise

    def cmd_new(self, p):
        # new file
        p = self._fsp(p)
        try:
            f = open(p, "wb")
        except OSError as e:
            if e.errno == errno.ENOENT:
                raise FileNotFoundError(p)
            raise
        f.close()
