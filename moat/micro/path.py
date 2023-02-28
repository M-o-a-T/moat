# This is an async version of mpy_repl.repl_connection.MpyPath

import io
import os
import sys
import pathlib
import binascii
import hashlib
import stat
import anyio
from .proto import RemoteError
from subprocess import CalledProcessError

import logging
logger = logging.getLogger(__name__)

class _MoatPath(pathlib.PurePosixPath):  # pathlib.PosixPath
    __slots__ = ('_repl', '_stat_cache')

    def connect_repl(self, repl):
        """Connect object to remote connection."""
        self._repl = repl
        return self  # allow method joining

    def _with_stat(self, st):
        self._stat_cache = os.stat_result(st)
        return self

    # methods to override to connect to repl

    def with_name(self, name):
        return super().with_name(name).connect_repl(self._repl)

    def with_suffix(self, suffix):
        return super().with_suffix(suffix).connect_repl(self._repl)

    def relative_to(self, *other):
        return super().relative_to(*other).connect_repl(self._repl)

    def joinpath(self, *args):
        return super().joinpath(*args).connect_repl(self._repl)

    def __truediv__(self, key):
        return super().__truediv__(key).connect_repl(self._repl)

    def __rtruediv__(self, key):
        return super().__rtruediv__(key).connect_repl(self._repl)

    @property
    def parent(self):
        return super().parent.connect_repl(self._repl)

    async def glob(self, pattern: str):
        """
        :param str pattern: string with optional wildcards.
        :return: generator over matches (MpyPath objects)

        Pattern match files on remote.
        """
        if pattern.startswith('/'):
            pattern = pattern[1:]   # XXX
        parts = pattern.split('/')
        # print('glob', self, pattern, parts)
        if not parts:
            return
        elif len(parts) == 1:
            async for r in self.iterdir():
                if r.match(pattern):
                    yield r
        else:
            remaining_parts = '/'.join(parts[1:])
            if parts[0] == '**':
                raise NotImplementedError
                #for dirpath, dirnames, filenames in walk(self):
                #    for path in filenames:
                #        if path.match(remaining_parts):
                #            yield path
            else:
                for path in self.iterdir():
                    if (await path.is_dir()) and path.relative_to(path.parent).match(parts[0]):  # XXX ?
                        async for r in path.glob(remaining_parts):
                            yield r


class MoatDevPath(_MoatPath):
    """
    This object represents a file or directory (existing or not) on the
    target board.

    This is the implementation that connects to the REPL directly.
    To actually modify the target, `connect_repl()` must have
    been called.
    """
    # methods that access files

    async def stat(self) -> os.stat_result:
        """
        Return stat information about path on remote. The information is cached
        to speed up operations.
        """
        if getattr(self, '_stat_cache', None) is None:
            st = await self._repl.evaluate(f'import os; print(os.stat({self.as_posix()!r}))')
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

    async def unlink(self):
        """
        :raises FileNotFoundError:

        Delete file. See also :meth:`rmdir`.
        """
        self._stat_cache = None
        await self._repl.evaluate(f'import os; print(os.remove({self.as_posix()!r}))')

    async def rename(self, path_to):
        """
        :param path_to: new name
        :return: new path object
        :raises FileNotFoundError: Source is not found
        :raises FileExistsError: Target already exits

        Rename file or directory. Source and target path need to be on the same
        filesystem.
        """
        self._stat_cache = None
        await self._repl.evaluate(f'import os; print(os.rename({self.as_posix()!r}, {path_to.as_posix()!r}))')
        return self.with_name(path_to)  # XXX, moves across dirs

    async def mkdir(self, parents=False, exist_ok=False):
        """
        :param parents: When true, create parent directories
        :param exist_ok: No error if the directory does not exist
        :raises FileNotFoundError:

        Create new directory.
        """
        try:
            return await self._repl.evaluate(f'import os; print(os.mkdir({self.as_posix()!r}))')
        except FileExistsError as e:
            if exist_ok:
                pass
            else:
                raise
        except FileNotFoundError:
            if parents:
                await self.parent.mkdir()
                await self.mkdir()
            else:
                raise

    async def rmdir(self):
        """
        :raises FileNotFoundError:

        Remove (empty) directory
        """
        await self._repl.evaluate(f'import os; print(os.rmdir({self.as_posix()!r}))')
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
            f'import ubinascii; _f = open({self.as_posix()!r}, "rb"); _mem = memoryview(bytearray(512))\n'
            'def _b(blocks=8):\n'
            '  print("[")\n'
            '  for _ in range(blocks):\n'
            '    n = _f.readinto(_mem)\n'
            '    if not n: break\n'
            '    print(ubinascii.b2a_base64(_mem[:n]), ",")\n'
            '  print("]")')
        while True:
            blocks = await self._repl.evaluate(f'_b({n_blocks})')
            if not blocks:
                break
            for block in blocks:
                yield binascii.a2b_base64(block)
        await self._repl.exec('_f.close(); del _f, _b')

    async def read_bytes(self) -> bytes:
        """
        :returns: file contents
        :rtype: bytes

        Return the contents of a remote file as byte string.
        """
        res = []
        async for r in self.read_as_stream():
            res.append(r)
        return b''.join(res)

    async def write_bytes(self, data, chunk=512) -> int:
        """
        :param bytes contents: Data

        Write contents (expected to be bytes) to a file on the target.
        """
        self._stat_cache = None
        if not isinstance(data, (bytes, bytearray,memoryview)):
            raise TypeError(f'contents must be bytes/bytearray, got {type(data)} instead')
        await self._repl.exec(f'from ubinascii import a2b_base64 as a2b; _f = open({self.as_posix()!r}, "wb")')
        # write in chunks
        with io.BytesIO(data) as local_file:
            while True:
                block = local_file.read(chunk)
                if not block:
                    break
                await self._repl.exec(f'_f.write(a2b({binascii.b2a_base64(block).rstrip()!r}))')
        await self._repl.exec('_f.close(); del _f, a2b')
        return len(data)

    # read_text(), write_text()

    async def iterdir(self):
        """
        Return iterator over items in given remote path.
        """
        if not self.is_absolute():
            raise ValueError(f'only absolute paths are supported (beginning with "/"): {self!r}')
        # simple version
        # remote_paths = self._repl.evaluate(f'import os; print(os.listdir({self.as_posix()!r}))')
        # return [(self / p).connect_repl(self._repl) for p in remote_paths]
        # variant with pre-loading stat info
        posix_path_slash = self.as_posix()
        if not posix_path_slash.endswith('/'):
            posix_path_slash += '/'
        remote_paths_stat = await self._repl.evaluate(
            'import os; print("[")\n'
            f'for n in os.listdir({self.as_posix()!r}): print("[", repr(n), ",", os.stat({posix_path_slash!r} + n), "],")\n'
            'print("]")')
        for p, st in remote_paths_stat:
            yield (self / p)._with_stat(st)

    # custom extension methods

    async def sha256(self) -> bytes:
        """
        :returns: hash over file contents

        Calculate a SHA256 over the file contents and return the digest.
        """
        try:
            await self._repl.exec(
                'import uhashlib; _h = uhashlib.sha256(); _mem = memoryview(bytearray(512))\n'
                f'with open({self.as_posix()!r}, "rb") as _f:\n'
                '  while True:\n'
                '    n = _f.readinto(_mem)\n'
                '    if not n: break\n'
                '    _h.update(_mem[:n])\n'
                'del n, _f, _mem\n')
        except ImportError:
            # fallback if no hashlib is available: download and hash here.
            try:
                _h = hashlib.sha256()
                async for block in self.read_as_stream():
                    _h.update(block)
                return _h.digest()
            except FileNotFoundError:
                return b''
        except OSError:
            hash_value = b''
        else:
            hash_value = await self._repl.evaluate('print(_h.digest()); del _h')
        return hash_value


class MoatFSPath(_MoatPath):
    """
    This object represents a file or directory (existing or not) on the
    target board.

    This is the implementation that connects via MoaT "f*" commands.
    To actually modify the target, `connect_repl()` must have
    been called.
    """
    # methods that access files

    async def _req(self, cmd, **kw):
        return await self._repl.send("f"+cmd, **kw)

#>>> os.stat_result((1,2,3,4,5,6,7,8,9,10))
#os.stat_result(st_mode=1, st_ino=2, st_dev=3, st_nlink=4, st_uid=5, st_gid=6, st_size=7, st_atime=8, st_mtime=9, st_ctime=10)

    async def stat(self) -> os.stat_result:
        """
        Return stat information about path on remote. The information is cached
        to speed up operations.
        """
        if getattr(self, '_stat_cache', None) is None:
            st = await self._req("stat", p=self.as_posix())
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

    async def unlink(self):
        """
        :raises FileNotFoundError:

        Delete file. See also :meth:`rmdir`.
        """
        self._stat_cache = None
        await self._req("rm", p=self.as_posix())

    async def rename(self, path_to):
        """
        :param path_to: new name
        :return: new path object
        :raises FileNotFoundError: Source is not found
        :raises FileExistsError: Target already exits

        Rename file or directory. Source and target path need to be on the same
        filesystem.
        """
        self._stat_cache = None
        await self._req("rm", s=self.as_posix(), d=path_to.as_posix())
        return self.with_name(path_to)  # XXX, moves across dirs

    async def mkdir(self, parents=False, exist_ok=False):
        """
        :param parents: When true, create parent directories
        :param exist_ok: No error if the directory does not exist
        :raises FileNotFoundError:

        Create new directory.
        """
        self._stat_cache = None
        try:
            return await self._req("mkdir", p=self.as_posix())
        except FileNotFoundError:
            if parents:
                await self.parent.mkdir(parents=True)
                return await self._req("mkdir", p=self.as_posix())
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
        return await self._req("rmdir", p=self.as_posix())
        self._stat_cache = None

    async def read_as_stream(self, chunk=128):
        """
        :returns: async Iterator
        :rtype: Iterator of bytes

        Iterate over blocks (`bytes`) of a remote file.
        """
        fd = await self._req("open", p=self.as_posix(), m="r")
        try:
            off=0
            while True:
                d = await self._req("rd", fd=fd,off=off, n=chunk)
                if not d:
                    break
                off += len(d)
                yield d
        finally:
            await self._req("cl", fd=fd)

    async def read_bytes(self, chunk=128) -> bytes:
        """
        :returns: file contents
        :rtype: bytes

        Return the contents of a remote file as byte string.
        """
        res = []
        async for r in self.read_as_stream(chunk=chunk):
            res.append(r)
        return b''.join(res)

    async def write_bytes(self, data, chunk=128) -> int:
        """
        :param bytes contents: Data

        Write contents (expected to be bytes) to a file on the target.
        """
        self._stat_cache = None
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise TypeError(f'contents must be a buffer, got {type(data)} instead')
        fd = await self._req("open", p=self.as_posix(), m="w")
        try:
            off=0
            while off < len(data):
                n = await self._req("wr", fd=fd, off=off, data=data[off:off+chunk])
                if not n:
                    raise EOFError
                off += n

        finally:
            await self._req("cl", fd=fd)

    # read_text(), write_text()

    async def iterdir(self):
        """
        Return iterator over items in given remote path.
        """
        if not self.is_absolute():
            raise ValueError(f'only absolute paths are supported (beginning with "/"): {self!r}')
        d = await self._req("dir", p=self.as_posix())
        for n in d:
            yield self/n
            # TODO add stat

    async def sha256(self) -> bytes:
        """
        :returns: hash over file contents

        Calculate a SHA256 over the file contents and return the digest.
        """
        return await self._req("hash",p=self.as_posix())


async def sha256(p):
    """
    Calculate a SHA256 of the file contents at @p.
    """
    try:
        return await p.sha256()
    except AttributeError:
        _h = hashlib.sha256()
        if hasattr(p,"read_as_stream"):
            async for block in p.read_as_stream():
                _h.update(block)
        else:
            async with await p.open("rb") as _f:
                _h.update(await _f.read())

        return _h.digest()


async def _nullcheck(p):
    """Null check function, always True"""
    if await p.is_dir():
        return p.name != "__pycache__"
    if p.suffix in (".py",".mpy", ".state"):
        return True
    logger.info("Ignored: %s", p)
    return False


async def copytree(src,dst,check=_nullcheck, cross=None):
    """
    Copy a file tree from @src to @dst.
    Skip files/subtrees for which "await check(src)" is False.
    (@src is never checked.)

    Files are copied if their size or content hash differs.

    Returns the number of modified files.
    """
    from .main import ABytes
    if await src.is_file():
        if src.suffix == ".py" and str(dst) not in ("/boot.py","boot.py","/main.py","main.py"):
            if cross:
                try:
                    p = str(src)
                    if (pi := p.find("/_embed/")) > 0:
                        p = p[pi+8:]
                    if p.startswith("lib/moat/"):
                        p = p[9:]
                    data = await anyio.run_process([cross, str(src), "-s", p, "-o", "/dev/stdout"])
                except CalledProcessError as exc:
                    print(exc.stderr.decode("utf-8"), file=sys.stderr)
                    pass
                else:
                    src = ABytes(src.with_suffix(".mpy"),data.stdout)
                    try:
                        await dst.unlink()
                    except (OSError,RemoteError):
                        pass
                    dst = dst.with_suffix(".mpy")
            else:
                try:
                    await dst.with_suffix(".mpy").unlink()
                except (OSError,RemoteError):
                    pass

        s1 = (await src.stat()).st_size
        try:
            s2 = (await dst.stat()).st_size
        except FileNotFoundError:
            s2 = -1
            await dst.parent.mkdir(parents=True, exist_ok=True)
        except RemoteError as err:
            if err.args[0] != "fn":
                raise
            s2 = -1
        if s1 == s2:
            h1 = await sha256(src)
            h2 = await sha256(dst)
            if h1 != h2:
                s2 = -1
        if s1 != s2:
            await dst.write_bytes(await src.read_bytes())
            logger.info("Copy: updated %s > %s", src,dst)
            return 1
        else:
            logger.debug("Copy: unchanged %s > %s", src,dst)
            return 0
    else:
        try:
            s = await dst.stat()
        except (OSError,RemoteError):
            await dst.mkdir(parents=True)

        logger.info("Copy: dir %s > %s", src,dst)
        n = 0
        if not await dst.exists():
            await dst.mkdir()
        async for s in src.iterdir():
            if not await check(s):
                continue
            d = dst/s.name
            n += await copytree(s,d, check=check, cross=cross)
        return n

