"""
This module contains an async version of mpy_repl.repl_connection.MpyPath,
and an equivalent that uses the MoaT file access protocol

"""

# CPython only

from __future__ import annotations

import anyio
import binascii
import hashlib
import io
import logging
import os
import stat
import sys
from contextlib import suppress
from pathlib import Path

from moat.util import attrdict
from moat.lib.codec.errors import RemoteError
from moat.util.exec import CalledProcessError, run

logger = logging.getLogger(__name__)


class ABytes(io.BytesIO):
    """
    An async-IO-mimicing version of `io.BytesIO`.
    """

    def __init__(self, name, data):
        super().__init__()
        self.name = name
        self.write(data)
        self.suffix = Path(name).suffix

    def __str__(self):
        return str(self.name)

    async def open(self, mode):  # noqa:ARG002 pylint: disable=unused-argument
        "reset the buffer pointer"
        self.seek(0, 0)
        return self

    async def read_bytes(self):
        "return the current buffer"
        return self.getbuffer()

    async def sha256(self, l: int | None = None):  # noqa: E741
        "hash the current buffer"
        _h = hashlib.sha256()
        _h.update(self.getbuffer())
        res = _h.digest()
        if l is not None:
            res = res[:l]
        return res

    async def gitsha1(self):
        "hash the current buffer"
        _h = hashlib.sha1()  # noqa:S324  # sha1
        _h.update(f"blob {len(self.getbuffer())}\0".encode())
        _h.update(self.getbuffer())
        return _h.digest()

    def close(self):
        "does nothing"
        # pylint:disable=unnecessary-pass

    async def is_dir(self):
        "returns False"
        return False

    async def is_file(self):
        "returns True"
        return True

    async def stat(self, follow_symlinks=False):  # noqa:ARG002 pylint: disable=unused-argument
        "returns the size. All other stat fields are empty"
        res = attrdict()
        res.st_size = len(self.getbuffer())
        return res


class APath(anyio.Path):
    "anyio.Path, enhanced with a couple of our methods"

    async def sha256(self, l=None) -> bytes:  # noqa: E741
        """
        :returns: hash over file contents

        Calculate a SHA256 over the file contents and return the digest.
        """
        _h = hashlib.sha256()
        async for block in self.read_as_stream():
            _h.update(block)
        res = _h.digest()
        if l is not None:
            res = res[:l]
        return res

    async def gitsha1(self):
        """
        :returns: hash over file contents

        Calculate a SHA1 over the file contents, the way "git" does it.
        """
        _h = hashlib.sha1()  # noqa:S324  # sha1
        sz = (await self.stat()).st_size
        _h.update(f"blob {sz}\0".encode())
        async for block in self.read_as_stream():
            _h.update(block)
        return _h.digest()

    async def read_as_stream(self, chunk=4096):  # noqa:ARG002
        """
        :returns: async Iterator
        :rtype: Iterator of bytes

        Iterate over blocks (`bytes`) of a remote file.
        """
        # pylint:disable=unused-argument

        fd = await self.open("r")
        try:
            d = await self.read_bytes()
            yield d
        except EOFError:
            pass

        finally:
            await fd.close()


class MoatPath(anyio.Path):  # pathlib.PosixPath
    "abstract superclass for MoaT-connected async file access"

    _stat_cache = None
    _repl = None

    def connect_repl(self, repl):
        """Connect object to remote connection."""
        self._repl = repl
        return self  # allow method joining

    def _with_stat(self, st):
        self._stat_cache = os.stat_result(st)
        return self

    # methods to override to connect to repl

    def with_name(self, name):
        "set name"
        # pylint: disable=no-member
        return type(self)(super().with_name(name)).connect_repl(self._repl)

    def with_suffix(self, suffix):
        "set suffix"
        # pylint: disable=no-member
        return type(self)(super().with_suffix(suffix)).connect_repl(self._repl)

    def relative_to(self, *other):
        "return relative path"
        # pylint: disable=no-member
        return type(self)(super().relative_to(*other)).connect_repl(self._repl)

    def joinpath(self, *args):
        "join paths"
        # pylint: disable=no-member
        return type(self)(super().joinpath(*args)).connect_repl(self._repl)

    def __truediv__(self, key):
        # pylint: disable=no-member
        return type(self)(super().__truediv__(key)).connect_repl(self._repl)

    @property
    def parent(self):
        "parent directory"
        # pylint: disable=no-member
        return type(self)(super().parent).connect_repl(self._repl)

    async def glob(self, pattern: str):  # pylint:disable=invalid-overridden-method
        """
        :param str pattern: string with optional wildcards.
        :return: generator over matches (MpyPath objects)

        Pattern match files on remote.
        """
        pattern = pattern.removeprefix("/")  # XXX
        parts = pattern.split("/")
        # print('glob', self, pattern, parts)
        if not parts:
            return
        elif len(parts) == 1:
            async for r in self.iterdir():
                if r.match(pattern):
                    yield r
        else:
            remaining_parts = "/".join(parts[1:])
            # pylint:disable=no-else-raise
            if parts[0] == "**":
                raise NotImplementedError
                # for dirpath, dirnames, filenames in walk(self):
                # for path in filenames:
                # if path.match(remaining_parts):
                # yield path
            else:
                for path in self.iterdir():
                    if (await path.is_dir()) and path.relative_to(path.parent).match(
                        parts[0],
                    ):  # XXX ?
                        async for r in path.glob(remaining_parts):
                            yield r

    async def iterdir(self):  # pylint:disable=invalid-overridden-method
        "list a directory under this path."
        raise NotImplementedError


class MoatDevPath(MoatPath):
    """
    This object represents a file or directory (existing or not) on the
    target board.

    This is the implementation that connects to the REPL directly.
    To actually modify the target, `connect_repl()` must have
    been called.
    """

    # methods that access files

    async def stat(self, *, follow_symlinks=False) -> os.stat_result:  # noqa:ARG002
        """
        Return stat information about path on remote. The information is cached
        to speed up operations.
        """
        if self._stat_cache is None:
            st = await self._repl.evaluate(
                f"import os; print(os.stat({self.as_posix()!r}))",
                quiet=True,
            )
            self._stat_cache = os.stat_result(st)
        return self._stat_cache

    async def exists(self):
        """Return True if target exists"""
        try:
            await self.stat()
        except FileNotFoundError:
            return False
        else:
            return True

    async def is_dir(self):
        """Return True if target exists and is a directory"""
        try:
            return ((await self.stat()).st_mode & stat.S_IFDIR) != 0
        except FileNotFoundError:
            return False

    async def is_file(self):
        """Return True if target exists and is a regular file"""
        try:
            return ((await self.stat()).st_mode & stat.S_IFREG) != 0
        except FileNotFoundError:
            return False

    async def unlink(self, missing_ok=False):
        """
        :raises FileNotFoundError:

        Delete file. See also :meth:`rmdir`.
        """
        self._stat_cache = None
        try:
            await self._repl.evaluate(
                f"import os; print(os.remove({self.as_posix()!r}))",
                quiet=True,
            )
        except FileNotFoundError:
            if not missing_ok:
                raise

    async def rename(self, target):
        """
        :param target: new name
        :return: new path object
        :raises FileNotFoundError: Source is not found
        :raises FileExistsError: Target already exits

        Rename file or directory. Source and target path need to be on the same
        filesystem.
        """
        self._stat_cache = None
        await self._repl.evaluate(
            f"import os; print(os.rename({self.as_posix()!r}, {target.as_posix()!r}))",
            quiet=True,
        )
        return self.with_name(target)  # XXX, moves across dirs

    async def mkdir(self, mode=0o755, parents=False, exist_ok=False):  # noqa:ARG002
        """
        :param parents: When true, create parent directories
        :param exist_ok: No error if the directory does not exist
        :param mode: ignored.
        :raises FileNotFoundError:

        Create new directory.
        """
        try:
            return await self._repl.evaluate(
                f"import os; print(os.mkdir({self.as_posix()!r}))",
                quiet=True,
            )
        except FileExistsError:
            if exist_ok:
                pass
            else:
                raise
        except FileNotFoundError:
            if parents:
                await self.parent.mkdir(parents=True)
                await self.mkdir()
            else:
                raise

    async def rmdir(self):
        """
        :raises FileNotFoundError:

        Remove (empty) directory
        """
        await self._repl.evaluate(f"import os; print(os.rmdir({self.as_posix()!r}))", quiet=True)
        self._stat_cache = None

    async def read_as_stream(self):
        """
        :returns: async Iterator
        :rtype: Iterator of bytes

        Iterate over blocks (`bytes`) of a remote file.
        """
        # reading (lines * linesize) must not take more than 1sec and 2kB target RAM!
        n_blocks = max(1, self._repl.serial.baudrate // 5120)
        await self._repl.exec(
            f'import ubinascii; _f = open({self.as_posix()!r}, "rb"); '
            "_mem = memoryview(bytearray(512))\n"
            "def _b(blocks=8):\n"
            '  print("[")\n'
            "  for _ in range(blocks):\n"
            "    n = _f.readinto(_mem)\n"
            "    if not n: break\n"
            '    print(ubinascii.b2a_base64(_mem[:n]), ",")\n'
            '  print("]")',
            quiet=True,
        )
        while True:
            blocks = await self._repl.evaluate(f"_b({n_blocks})", quiet=True)
            if not blocks:
                break
            for block in blocks:
                yield binascii.a2b_base64(block)
        await self._repl.exec("_f.close(); del _f, _b", quiet=True)

    async def read_bytes(self) -> bytes:
        """
        :returns: file contents
        :rtype: bytes

        Return the contents of a remote file as byte string.
        """
        res = []
        async for r in self.read_as_stream():
            res.append(r)
        return b"".join(res)

    async def write_bytes(self, data, chunk=512) -> int:
        """
        :param bytes contents: Data

        Write contents (expected to be bytes) to a file on the target.
        """
        self._stat_cache = None
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise TypeError(f"contents must be bytes/bytearray, got {type(data)} instead")
        await self._repl.exec(
            f'from binascii import a2b_base64 as _a2b; _f = open({self.as_posix()!r}, "wb")',
            quiet=True,
        )
        # write in chunks
        with io.BytesIO(data) as local_file:
            while True:
                block = local_file.read(chunk)
                if not block:
                    break
                await self._repl.exec(
                    f"_f.write(_a2b({binascii.b2a_base64(block).rstrip()!r}))",
                    quiet=True,
                )
        await self._repl.exec("_f.close(); del _f, _a2b", quiet=True)
        return len(data)

    # read_text(), write_text()

    async def iterdir(self):
        """
        Return iterator over items in given remote path.
        """
        if not self.is_absolute():
            raise ValueError(f'only absolute paths are supported (beginning with "/"): {self!r}')
        # simple version
        # remote_paths = self._repl.evaluate(
        #     f'import os; print(os.listdir({self.as_posix()!r}))', quiet=True)
        # return [(self / p).connect_repl(self._repl) for p in remote_paths]
        # variant with pre-loading stat info
        posix_path_slash = self.as_posix()
        if not posix_path_slash.endswith("/"):
            posix_path_slash += "/"
        remote_paths_stat = await self._repl.evaluate(
            'import os; print("[")\n'
            f"for n in os.listdir({self.as_posix()!r}): "
            '    print("[", repr(n), ",", os.stat({posix_path_slash!r} + n), "],")\n'
            'print("]")',
            quiet=True,
        )
        for p, st in remote_paths_stat:
            yield (self / p)._with_stat(st)  # noqa:SLF001 pylint:disable=protected-access

    # custom extension methods

    async def sha256(self, l: int | None = None) -> bytes:  # noqa: E741
        """
        :returns: hash over file contents

        Calculate a SHA256 over the file contents and return the digest.
        """
        try:
            await self._repl.exec(
                "import hashlib; _h = hashlib.sha256(); _mem = memoryview(bytearray(512))\n"
                f'with open({self.as_posix()!r}, "rb") as _f:\n'
                "  while True:\n"
                "    _n = _f.readinto(_mem)\n"
                "    if not _n: break\n"
                "    _h.update(_mem[:_n])\n"
                "del _n, _f, _mem\n",
                quiet=True,
            )
        except ImportError:
            # fallback if no hashlib is available: download and hash here.
            try:
                _h = hashlib.sha256()
                async for block in self.read_as_stream():
                    _h.update(block)
                return _h.digest()
            except FileNotFoundError:
                return b""
        except OSError:
            hash_value = b""
        else:
            if l is None:
                hash_value = await self._repl.evaluate("print(_h.digest()); del _h", quiet=True)
            else:
                hash_value = await self._repl.evaluate(
                    f"print(_h.digest()[:{l}]); del _h",
                    quiet=True,
                )
        return hash_value


class MoatFSPath(MoatPath):
    """
    This object represents a file or directory (existing or not) on the
    target board.

    This is the implementation that connects via MoaT "f*" commands.

    To actually modify the target, `connect_repl()` must have
    been called.
    """

    # methods that access files

    async def _req(self, cmd, *a, **kw):
        res = await self._repl.cmd(cmd, *a, **kw)
        if res.kw:
            return res.kw
        if len(res) == 1:
            return res[0]
        return res.args

    # >>> os.stat_result((1,2,3,4,5,6,7,8,9,10))
    # os.stat_result(st_mode=1, st_ino=2, st_dev=3, st_nlink=4,
    #                st_uid=5, st_gid=6, st_size=7, st_atime=8, st_mtime=9, st_ctime=10)

    async def stat(self, *, follow_symlinks=False) -> os.stat_result:  # noqa:ARG002
        """
        Return stat information about path on remote. The information is cached
        to speed up operations.
        """
        if self._stat_cache is None:
            st = await self._req("stat", self.as_posix(), v=True)
            self._stat_cache = os.stat_result(st["d"])
        return self._stat_cache

    async def exists(self):
        """Return True if target exists"""
        try:
            await self.stat()
        except FileNotFoundError:
            return False
        else:
            return True

    async def is_dir(self):
        """Return True if target exists and is a directory"""
        try:
            return stat.S_ISDIR((await self.stat()).st_mode)
        except FileNotFoundError:
            return False

    async def is_file(self):
        """Return True if target exists and is a regular file"""
        try:
            return stat.S_ISREG((await self.stat()).st_mode)
        except FileNotFoundError:
            return False

    async def unlink(self, missing_ok=False):
        """
        :raises FileNotFoundError:

        Delete file. See also :meth:`rmdir`.
        """
        self._stat_cache = None
        try:
            await self._req("rm", self.as_posix())
        except FileNotFoundError:
            if not missing_ok:
                raise

    async def rename(self, target):
        """
        :param target: new name
        :return: new path object
        :raises FileNotFoundError: Source is not found
        :raises FileExistsError: Target already exits

        Rename file or directory. Source and target path need to be on the same
        filesystem.
        """
        self._stat_cache = None
        await self._req("mv", self.as_posix(), target.as_posix())
        return self.with_name(target)  # XXX, moves across dirs

    async def mkdir(self, mode=0o755, parents=False, exist_ok=False):  # noqa:ARG002
        """
        :param parents: When true, create parent directories
        :param exist_ok: No error if the directory does not exist
        :raises FileNotFoundError:

        Create new directory.
        """
        self._stat_cache = None
        try:
            return await self._req("mkdir", self.as_posix())
        except FileNotFoundError:
            if parents:
                await self.parent.mkdir(parents=True)
                return await self._req("mkdir", self.as_posix())
            else:
                raise
        except FileExistsError:
            if exist_ok:
                pass
            else:
                raise

    async def rmdir(self):
        """
        :raises FileNotFoundError:

        Remove (empty) directory
        """
        res = await self._req("rmdir", self.as_posix())
        self._stat_cache = None
        return res

    async def read_as_stream(self, chunk=128):
        """
        :returns: async Iterator
        :rtype: Iterator of bytes

        Iterate over blocks (`bytes`) of a remote file.
        """
        fd = await self._req("open", self.as_posix(), m="r")
        try:
            off = 0
            while True:
                d = await self._req("rd", fd, off, n=chunk)
                if not d:
                    break
                off += len(d)
                yield d
        finally:
            await self._req("cl", fd)

    async def read_bytes(self, chunk=128) -> bytes:
        """
        :returns: file contents
        :rtype: bytes

        Return the contents of a remote file as byte string.
        """
        res = []
        async for r in self.read_as_stream(chunk=chunk):
            res.append(r)
        return b"".join(res)

    async def write_bytes(self, data, chunk=128) -> int:
        """
        :param bytes contents: Data

        Write contents (expected to be bytes) to a file on the target.
        """
        self._stat_cache = None
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise TypeError(f"contents must be a buffer, got {type(data)} instead")
        fd = await self._req("open", self.as_posix(), m="w")
        try:
            off = 0
            while off < len(data):
                n = await self._req("wr", fd, off, d=data[off : off + chunk])
                if not n:
                    raise EOFError
                off += n

        finally:
            await self._req("cl", fd)

    # read_text(), write_text()

    async def iterdir(self):
        """
        Return iterator over items in given remote path.
        """
        if not self.is_absolute():
            raise ValueError(f'only absolute paths are supported (beginning with "/"): {self!r}')
        d = await self._req("dir", self.as_posix())
        for n in d:
            yield self / n
            # TODO add stat

    async def sha256(self, l: int | None = None) -> bytes:  # noqa: E741
        """
        :returns: hash over file contents

        Calculate a SHA256 over the file contents and return the digest.
        """
        return await self._req("hash", self.as_posix(), l=l)


async def sha256(p, l: int | None = None):  # noqa: E741
    """
    Calculate a SHA256 of the file contents at @p.
    """
    try:
        return await p.sha256(l=l)
    except AttributeError:
        _h = hashlib.sha256()
        if hasattr(p, "read_as_stream"):
            async for block in p.read_as_stream():
                _h.update(block)
        else:
            async with await p.open("rb") as _f:
                _h.update(await _f.read())

        res = _h.digest()
        if l is not None:
            res = res[:l]
        return res


async def _nullcheck(p):
    """Null check function, always True"""
    if await p.is_dir():
        return p.name != "__pycache__"
    if p.suffix in (".py", ".mpy", ".state"):
        return True
    logger.info("Ignored: %s", p)
    return False


async def f_eq(src, dst):
    """check whether twofiles are the same"""
    s1 = (await src.stat()).st_size
    try:
        s2 = (await dst.stat()).st_size
    except FileNotFoundError:
        s2 = -1
    except RemoteError as err:
        if err.args[0] != "fn":
            raise
        s2 = -1
    if s1 == s2:
        h1 = await sha256(src, 12)
        h2 = await sha256(dst, 12)
        if h1 != h2:
            s2 = -1

    return s1 == s2


async def copytree(
    src: APath, dst: MoatPath, wdst: MoatPath | None = None, check=None, drop=None, cross=None
):
    """
    Copy a file or directory tree from @src to @dst.
    Skip files/subtrees for which "await check(src)" is False.
    (@src is never checked.)

    Files are copied if their size or content hash differs.

    Returns the number of modified files.

    @drop is an async function with the destination file as input. If it
    returns `True` the file is deleted unconditionally, `False` (the
    default) does a standard sync-and-update, `None` ignores it.

    If @wdst is set, new files get written there; they will be deleted from @dst.
    """
    n = 0
    if wdst is None:
        wdst = dst
    if await src.is_file():
        if src.suffix == ".py":
            # here we replace "src" with a buffer containing the
            # corresponding mpy-cross output.

            dr = False if drop is None else await drop(dst)
            if dr:
                with suppress(FileNotFoundError):
                    await dst.unlink()
                    n += 1
                with suppress(FileNotFoundError):
                    await dst.with_suffix(".mpy").unlink()
                    n += 1
                return n

            if dr is None:
                return 0

            if wdst is not dst:
                with suppress(OSError, RemoteError):
                    await dst.unlink()
                with suppress(OSError, RemoteError):
                    await dst.with_suffix(".mpy").unlink()

            if cross:
                try:
                    p = str(src)
                    if (pi := p.find("/_embed/lib/")) > 0:
                        p = p[pi + 12 :]
                    data = await run(cross, str(src), "-s", p, "-o", "/dev/stdout", capture="raw")
                except CalledProcessError as exc:
                    print(exc.stderr.decode("utf-8"), file=sys.stderr)
                    # copy this file unmodified
                else:
                    src = ABytes(src.with_suffix(".mpy"), data)
                    wdst = wdst.with_suffix(".mpy")
                    with suppress(OSError, RemoteError):
                        if await f_eq(src, wdst):
                            return 0
                        await wdst.unlink()
            else:
                with suppress(OSError, RemoteError):
                    await dst.with_suffix(".mpy").unlink()

        if wdst is not dst:
            print(" Write:", dst, "       ", end="\r", file=sys.stderr)
            new = True
            with suppress(OSError, RemoteError):
                await dst.unlink()
                new = False
            await wdst.parent.mkdir(parents=True, exist_ok=True)
            await wdst.write_bytes(await src.read_bytes())
            logger.info("Copy: %s: %s", "new" if new else "update", dst)
            return 1

        if await f_eq(src, dst):
            return 0

        await wdst.parent.mkdir(parents=True, exist_ok=True)
        new = True
        with suppress(OSError, RemoteError):
            await wdst.unlink()
            new = False
        await wdst.write_bytes(await src.read_bytes())
        logger.info("Copy: %s: %s", "new" if new else "update", wdst)
        return 1

    else:
        if dst.name == "__pycache__":
            return 0
        if dst.name.startswith("."):
            return 0
        with suppress(OSError, RemoteError):
            s = await dst.stat()

        # logger.debug("Copy: dir %s > %s", src, dst)
        print("  Sync:", dst, "       ", end="\r", file=sys.stderr)
        sys.stderr.flush()
        async for s in src.iterdir():
            if check is not None and not await check(s):
                continue
            d = dst / s.name
            n += await copytree(
                s,
                d,
                check=check,
                cross=cross,
                drop=drop,
                wdst=None if wdst is dst else wdst / s.name,
            )
        return n


async def copy_over(src, dst, cross=None, wdst: anyio.Path | None = None):
    """
    Transfer a file tree from @src to @dst.

    This procedure verifies that the data arrived OK.
    """
    tn = 0
    if await src.is_file():
        if await dst.is_dir():
            dst /= src.name
    while n := await copytree(src, dst, cross=cross, wdst=wdst):
        tn += n
    #       if n == 1:
    #           logger.info("One file changed. Verifying.")
    #       else:
    #           logger.info("%d files changed. Verifying.", n)
    #   logger.info("Done. No (more) differences detected.")
    return tn
