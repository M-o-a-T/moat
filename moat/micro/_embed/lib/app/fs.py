"""
Access a satellite's Flash file system.
"""
from __future__ import annotations

import errno
import os

from moat.micro.cmd.base import BaseCmd
from moat.micro.errors import FileExistsError, FileNotFoundError


class Cmd(BaseCmd):
    """
    File system access.

    Set "root" to the file system path this command should apply to.
    """

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

    async def cmd_reset(self, p=None):
        "close all"
        for v in self._fd_cache.values():
            v.close()
        self._fd_cache = dict()

        if not p or p == "/":
            self._fs_prefix = ""
        elif p[0] == "/":
            self._fs_prefix = p
        else:
            self._fs_prefix += "/" + p

    async def cmd_open(self, p, m="r"):
        "open @f in binary mode @m (r,w)"
        p = self._fsp(p)
        try:
            f = open(p, m + "b")  # noqa:ASYNC101,SIM115
        except OSError as e:
            if e.errno == errno.ENOENT:
                raise FileNotFoundError(p) from None
            raise
        else:
            return self._add_f(f)

    async def cmd_rd(self, f, o=0, n=64):
        "read @n bytes from @f at offset @o"
        fh = self._fd(f)
        fh.seek(o)
        return fh.read(n)

    async def cmd_wr(self, f, d, o=0):
        "write @d to @f at offset @o"
        fh = self._fd(f)
        fh.seek(o)
        return fh.write(d)

    async def cmd_cl(self, f):
        "close @f"
        self._del_f(f)

    async def cmd_ls(self, p="", x=False):
        """
        dir of @p.

        Set @x to return a list of stat mappings::
        n: name
        t: time
        s: size
        """
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

    async def cmd_mkdir(self, p):
        "new dir at @p"
        p = self._fsp(p)
        os.mkdir(p)

    async def cmd_hash(self, p):
        """
        Hash the contents of @p, sha256
        """
        import hashlib

        _h = hashlib.sha256()
        _mem = memoryview(bytearray(512))

        p = self._fsp(p)
        with open(p, "rb") as _f:  # noqa:ASYNC101
            while True:
                n = _f.readinto(_mem)
                if not n:
                    break
                _h.update(_mem[:n])
        return _h.digest()

    async def cmd_stat(self, p, v=False):
        """
        State of @p.

        Returns a mapping::

            m: mode (f,d,?)
            s: size (files only)
            t: mod time
            d: state array

        @d will not be sent if @v is False.
        """
        p = self._fsp(p)
        try:
            s = os.stat(p)
        except OSError as e:
            if e.errno == errno.ENOENT:
                raise FileNotFoundError(p)  # noqa:TRY200
            raise
        if s[0] & 0x8000:  # file
            res = dict(m="f", s=s[6], t=s[7])
        elif s[0] & 0x4000:  # file
            res = dict(m="d", t=s[7])
        else:
            res = dict(m="?")
        if v:
            res[d] = s
        return res

    async def cmd_mv(self, s, d, x=None, n=False):
        """
        move file @s to @d.

        If @n is True, the destination must not exist
        @x is the name of a temp file; if set, it is used for swapping @s
        and @d.
        """
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

    async def cmd_rm(self, p):
        "unlink file @p"
        p = self._fsp(p)
        try:
            os.remove(p)
        except OSError as e:
            if e.errno == errno.ENOENT:
                raise FileNotFoundError(p)  # noqa:TRY200
            raise

    async def cmd_rmdir(self, p):
        "unlink dir @p"
        p = self._fsp(p)
        try:
            os.rmdir(p)
        except OSError as e:
            if e.errno == errno.ENOENT:
                raise FileNotFoundError(p)  # noqa:TRY200
            raise

    async def cmd_new(self, p):
        "new file @p"
        p = self._fsp(p)
        try:
            f = open(p, "wb")  # noqa:ASYNC101,SIM115
        except OSError as e:
            if e.errno == errno.ENOENT:
                raise FileNotFoundError(p)  # noqa:TRY200
            raise
        f.close()
