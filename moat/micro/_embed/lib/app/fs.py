"""
Access a satellite's Flash file system.
"""

from __future__ import annotations

import errno
import os

from moat.lib.codec.errors import FileExistsError, FileNotFoundError  # noqa:A004
from moat.micro.cmd.base import BaseCmd
from moat.util.compat import sleep_ms


def _fty(s, **r):
    # file type/size: stat array to dict
    sn = s[0]
    if sn & 0x8000:  # file
        m = "f"
    elif sn & 0x4000:  # file
        m = "d"
    else:
        m = "?"
    r["m"] = m

    if m == "f":
        r["s"] = s[6]
    if m != "?":
        r["t"] = s[7]
    return r


def _efix(f, p, *a):
    # fix errors
    try:
        return f(p, *a)
    except OSError as e:
        if e.errno == errno.ENOENT:
            raise FileNotFoundError(p) from None
        if e.errno == errno.EEXIST:
            raise FileExistsError(p) from None
        raise


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

    doc = dict(_d="File system access.", _c=dict(root="Path to file system root"))

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

    doc_reset = dict(_d="close all", p="str:set new prefix")

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

    doc_open = dict(_d="open file", _0="str:path", m="str:mode (r,w)", _r="int:fileid")

    async def cmd_open(self, p, m="r"):
        "open @f in binary mode @m (r,w)"
        p = self._fsp(p)
        f = _efix(open, p, m + "b")
        return self._add_f(f)

    doc_rd = dict(_d="read file", _0="int:fileid", _1="int:offset", n="int:length")

    async def cmd_rd(self, f, o=0, n=64):
        "read @n bytes from @f at offset @o"
        fh = self._fd(f)
        fh.seek(o)
        return fh.read(n)

    doc_wr = dict(_d="write file", _0="int:fileid", _1="int:offset", d="bytes:data")

    async def cmd_wr(self, f, o=0, d=None):
        "write @d to @f at offset @o"
        if d is None:
            raise ValueError("No Data")
        fh = self._fd(f)
        fh.seek(o)
        return fh.write(d)

    doc_cl = dict(_d="close file", _0="int:fileid")

    async def cmd_cl(self, f):
        "close @f"
        self._del_f(f)

    doc_ls = dict(_d="list dir", _0="str:path", x="bool:return mapping", _o="str|dict")

    async def cmd_ls(self, p="", x=False):
        """
        dir of @p.

        Set @x to return a list of stat mappings::
        n: name
        t: time
        s: size
        m: type
        """
        p = self._fsp(p)
        res = []
        if x:
            for n, *_ in os.ilistdir(p):
                await sleep_ms(1)
                st = os.stat(f"{p}/{n}")
                await sleep_ms(1)
                res.append(_fty(st, n=n))
        else:
            for n, *_ in os.ilistdir(p):
                await sleep_ms(1)
                res.append(n)
        return res

    doc_mkdir = dict(_d="make dir", _0="str:path")

    async def cmd_mkdir(self, p):
        "new dir at @p"
        p = self._fsp(p)
        _efix(os.mkdir, p)

    doc_hash = dict(_d="hash file", _0="str:path", l="int:prefixlen", _r="bytes:hash")

    async def cmd_hash(self, p: str, l: int | None = None):  # noqa: E741
        """
        Hash the contents of @p, sha256
        """
        import hashlib  # noqa: PLC0415

        _h = hashlib.sha256()
        _mem = memoryview(bytearray(512))

        p = self._fsp(p)
        with open(p, "rb") as _f:  # noqa:ASYNC230
            while True:
                n = _f.readinto(_mem)
                if not n:
                    break
                _h.update(_mem[:n])
        res = _h.digest()
        if l is not None:
            res = res[:l]
        return res

    doc_stat = dict(
        _d="stat file",
        _0="str:path",
        v="bool:include struct",
        _r=dict(m="int:mode", s="int:size", t="int:modtime", d="list:state struct"),
    )

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
        s = _efix(os.stat, p)
        res = _fty(s)
        if v:
            res["d"] = s
        return res

    doc_mv = dict(
        _d="rename/move file",
        _0="str:source",
        _1="str:dest",
        x="str:exchange temp",
        n="bool:dest must be new",
    )

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
                _efix(os.stat, q)
            except FileNotFoundError:
                pass
            else:
                raise FileExistsError(q)
        if x is None:
            os.rename(p, q)
        else:
            x = self._fsp(x)
            # exchange contents, via third file
            try:
                _efix(os.stat, x)
            except FileNotFoundError:
                pass
            else:
                raise FileExistsError(q)
            os.rename(p, x)
            os.rename(q, p)
            os.rename(x, q)

    doc_rm = dict(_d="remove file", _0="str:path")

    async def cmd_rm(self, p):
        "unlink file @p"
        p = self._fsp(p)
        _efix(os.remove, p)

    doc_rmdir = dict(_d="remove dir", _0="str:path")

    async def cmd_rmdir(self, p):
        "unlink dir @p"
        p = self._fsp(p)
        _efix(os.rmdir, p)

    doc_new = dict(_d="create file", _0="str:path")

    async def cmd_new(self, p):
        "new file @p"
        p = self._fsp(p)
        f = _efix(open, p, "wb")
        f.close()
