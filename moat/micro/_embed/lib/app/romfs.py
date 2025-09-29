"""
Access a satellite's Flash file system.
"""

from __future__ import annotations

import vfs

from moat.micro.cmd.base import BaseCmd


class Dev:
    "Mostly-byte-level abstraction for a ROMFS device"

    _wr = None

    def __init__(self, n):
        self.dev = vfs.rom_ioctl(2, n)
        self.buf = bytearray(self.dev.ioctl(5, 0))
        self.pos = 0

    @property
    def cur_blk(self):
        "current block number"
        return self.pos // len(self.buf)

    @property
    def cur_off(self):
        "offset in current block"
        return self.pos % len(self.buf)

    @property
    def buf_n(self):
        "device's number of buffers"
        return self.dev.ioctl(4, 0)

    @property
    def buf_sz(self):
        "device's buffer size"
        return len(self.buf)

    def seek(self, n: int):
        """go to @n, clears r/w flag"""
        if n == self.pos:
            return
        if n % len(self.buf):
            raise ValueError("block boundary only")
        if self._wr and self.pos % len(self.buf):
            raise RuntimeError("buffered write")
        self.pos = n
        self._wr = None

    def write(self, data: bytes):
        """write to the buffer"""
        if self._wr is False:
            raise ValueError("r/w")
        self._wr = True
        ld = len(data)
        if self.pos % len(self.buf) + ld > len(self.buf):
            raise ValueError("crosses block boundary")
        self.buf[self.cur_off : self.cur_off + ld] = data
        self.pos += ld
        if self.cur_off == 0:
            self.wrb()

    def wrb(self):
        """write the current buffer"""
        lb = len(self.buf)
        blk = self.cur_off // lb - (self.cur_off % lb == 0)
        self.dev.writeblocks(blk, self.buf)  # no offset given: auto-erase

    def read(self, n: int):
        """fetch @n bytes from the buffer"""
        if self._wr is False:
            raise ValueError("r/w")
        self._wr = False
        if self.cur_off % len(self.buf) == 0:
            self.rdb()
        np = self.pos % len(self.buf)
        if np + n > len(self.buf):
            raise ValueError("crosses block boundary")
        self.pos += n
        return memoryview(self.buf)[np : np + n]

    def rdb(self):
        """read the next buffer"""
        lb = len(self.buf)
        self.dev.readblocks(self.cur_off // lb, self.buf)

    def close(self):
        """flush the buffer"""
        if self._wr:
            self.wrb()
        self.seek(0)


class Cmd(BaseCmd):
    """
    ROM File system access.

    Set "root" to the file system path this command should apply to.
    """

    _dev_cache = None

    def __init__(self, cfg):
        super().__init__(cfg)
        self._dev_cache = dict()
        self._dev_pos = dict()

    def dev(self, n):  # noqa: D102
        try:
            return self._dev_cache[n].dev
        except KeyError:
            try:
                vfs.umount("/rom")
            except Exception:  # noqa:S110
                pass
            self._dev_cache[n] = dev = vfs.rom_ioctl(2, n)
            return dev

    doc_n = dict(_d="#ROMs", _r="int:n")

    async def cmd_n(self):
        "return the number of ROM filesystems"
        return vfs.rom_ioctl(1)

    doc_stat = dict(_d="get device sizes", _0="int:n", _r0="int:nblocks", _r1="int:blocksize")

    async def cmd_stat(self, dev: int):
        "device data"
        d = self.dev(dev)
        return d.buf_n, d.buf_sz

    doc_cl = dict(_d="close device file", _0="int:n")

    async def cmd_cl(self, dev: int):
        "'close' device N"
        dev = self._dev_cache.pop(dev)
        dev.close()
        return

    doc_rd = dict(_d="read FS", _0="int:dev", _1="int:offset", n="int:length")

    async def cmd_rd(self, dev: int = 0, o: int = 0, n: int = 64):
        "read @n bytes from @f at offset @o"
        dev = self.dev(dev)
        dev.seek(o)
        return dev.read(n)

    async def stream_rd(self, msg):  # noqa: D102
        dev = self.dev(msg[0])
        off = msg[1] if len(msg) > 1 else 0
        blk = msg[2] if len(msg) > 2 else 64
        nblk = dev.buf_sz * dev.buf_n
        nblk = (nblk + blk - 1) // blk
        off  # noqa:B018
        async with msg.stream_out() as st:
            while nblk > 0:
                nblk -= 1
                await st.send(dev.read(blk))
        dev.close()

    doc_wr = dict(_d="write FS", _0="int:dev", _1="int:offset", d="bytes:data")

    async def cmd_wr(self, dev, o=0, d=None):
        "write @d to @d at offset @o"
        dev = self.dev(dev)
        dev.seek(o)
        return dev.write(d)

    async def stream_wr(self, msg):  # noqa: D102
        dev = self.dev(msg[0])
        off = msg[1] if len(msg) > 1 else 0
        dev.seek(off)
        async with msg.stream_in() as st:
            async for (m,) in st:
                dev.write(m)
        dev.close()
