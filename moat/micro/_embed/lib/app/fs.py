"""
Access a satellite's file system.
"""

from __future__ import annotations

import errno
import os

from moat.lib.codec.errors import FileExistsError, FileNotFoundError  # noqa:A004
from moat.micro.cmd.base import LockBaseCmd
from moat.util.compat import to_thread

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.util import attrdict


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


class Cmd(LockBaseCmd):
    """
    File system access.

    Set "root" to the file system path this command should apply to.
    """

    _fd_last = 0
    _fd_cache = None

    def __init__(self, cfg: attrdict):
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

    def _fsp(self, p: str):
        if self._pre:
            p = self._pre + p
        if p == "":
            p = "/"
        # elif p == ".." or p.startswith("../") or "/../" in p: or p.endswith("/..")
        # raise FSError("nf")
        return p

    def _fd(self, fd: int):
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

    async def _del_f(self, fd: int):
        f = self._fd_cache.pop(fd)
        # log(f"{fd}!{repr(f)}")
        await to_thread(f.close)

    doc_reset = dict(_d="close all", p="str:set new prefix")

    async def cmd_reset(self, p: str | None = None):
        "close all"
        for v in self._fd_cache.values():
            await to_thread(v.close)
        self._fd_cache = dict()

        if not p or p == "/":
            self._fs_prefix = ""
        elif p[0] == "/":
            self._fs_prefix = p
        else:
            self._fs_prefix += "/" + p

    doc_open = dict(_d="open file", _0="str:path", m="str:mode (r,w)", _r="int:fileid")

    async def cmd_open(self, p: str, m: str = "r"):
        "open @f in binary mode @m (r,w)"
        p = self._fsp(p)
        f = await to_thread(_efix, open, p, m + "b")
        return self._add_f(f)

    doc_rd = dict(_d="read file", _0="int:fileid", _1="int:offset", n="int:length")

    async def cmd_rd(self, f: int, o: int = 0, n: int = 64):
        "read @n bytes from @f at offset @o"
        fh = self._fd(f)
        fh.seek(o)
        return await to_thread(fh.read, n)

    doc_wr = dict(_d="write file", _0="int:fileid", _1="int:offset", d="bytes:data")

    async def cmd_wr(self, f: int, o: int = 0, d: bytes = None):  # noqa: RUF013
        "write @d to @f at offset @o"
        if d is None:
            raise ValueError("No Data")
        fh = self._fd(f)
        fh.seek(o)
        return await to_thread(fh.write, d)

    doc_cl = dict(_d="close file", _0="int:fileid")

    async def cmd_cl(self, f):
        "close @f"
        await self._del_f(f)

    doc_ls = dict(_d="list dir", _0="str:path", x="bool:return mapping", _o="str|dict")

    async def cmd_ls(self, p: str = "", x: bool = False):
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
        it = await to_thread(os.ilistdir, p)

        def inext(it):
            try:
                return next(it)
            except StopIteration:
                return (None,)

        if x:
            while True:
                n, *_ = await to_thread(inext, it)
                if n is None:
                    break
                st = await to_thread(os.stat, f"{p}/{n}")
                res.append(_fty(st, n=n))
        else:
            while True:
                n, *_ = await to_thread(inext, it)
                if n is None:
                    break
                res.append(n)
        return res

    doc_mkdir = dict(_d="make dir", _0="str:path")

    async def cmd_mkdir(self, p: str):
        "new dir at @p"
        p = self._fsp(p)
        await to_thread(_efix, os.mkdir, p)

    doc_hash = dict(_d="hash file", _0="str:path", l="int:prefixlen", _r="bytes:hash")

    async def cmd_hash(self, p: str, l: int | None = None):  # noqa: E741
        """
        Hash the contents of @p, sha256
        """
        import hashlib  # noqa: PLC0415

        _h = hashlib.sha256()
        _mem = memoryview(bytearray(512))

        p = self._fsp(p)
        _f = await to_thread(open, p, "rb")
        try:
            while True:
                n = await to_thread(_f.readinto, _mem)
                if not n:
                    break
                _h.update(_mem[:n])
        finally:
            await to_thread(_f.close)
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

    async def cmd_stat(self, p: str, v: bool = False):
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
        s = await to_thread(_efix, os.stat, p)
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

    async def cmd_mv(self, s: str, d: str, x: str | None = None, n: bool = False):
        """
        move file @s to @d.

        If @n is True, the destination must not exist.

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
            await to_thread(os.rename, p, q)
        else:
            x = self._fsp(x)
            # exchange contents, via third file
            try:
                _efix(os.stat, x)
            except FileNotFoundError:
                pass
            else:
                raise FileExistsError(q)
            await to_thread(os.rename, p, x)
            await to_thread(os.rename, q, p)
            await to_thread(os.rename, x, q)

    doc_rm = dict(_d="remove file", _0="str:path")

    async def cmd_rm(self, p: str):
        "unlink file @p"
        p = self._fsp(p)
        await to_thread(_efix, os.remove, p)

    doc_rmdir = dict(_d="remove dir", _0="str:path")

    async def cmd_rmdir(self, p: str):
        "unlink dir @p"
        p = self._fsp(p)
        await to_thread(_efix, os.rmdir, p)

    doc_new = dict(_d="create file", _0="str:path")

    async def cmd_new(self, p: str):
        "new file @p"
        p = self._fsp(p)
        f = await to_thread(_efix, open, p, "wb")
        await to_thread(f.close)
