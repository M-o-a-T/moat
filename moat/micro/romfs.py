# MIT license; Copyright (c) 2022 Damien P. George
# © 2025 Matthias Urlichs

import struct, sys, os

try:
    from mpy_cross import run as mpy_cross_run
except ImportError:
    mpy_cross_run = None


class VfsRomWriter:
    ROMFS_HEADER = b"\xd2\xcd\x31"

    ROMFS_RECORD_KIND_UNUSED = 0
    ROMFS_RECORD_KIND_PADDING = 1
    ROMFS_RECORD_KIND_DATA_VERBATIM = 2
    ROMFS_RECORD_KIND_DATA_POINTER = 3
    ROMFS_RECORD_KIND_DIRECTORY = 4
    ROMFS_RECORD_KIND_FILE = 5

    def __init__(self, cross):
        self._dir_stack = [(None, bytearray())]
        self.cross = cross

    def _encode_uint(self, value):
        encoded = [value & 0x7F]
        value >>= 7
        while value != 0:
            encoded.insert(0, 0x80 | (value & 0x7F))
            value >>= 7
        return bytes(encoded)

    def _pack(self, kind, payload):
        return self._encode_uint(kind) + self._encode_uint(len(payload)) + payload

    def _extend(self, data):
        buf = self._dir_stack[-1][1]
        buf.extend(data)
        return len(buf)

    def finalise(self):
        _, data = self._dir_stack.pop()
        encoded_kind = VfsRomWriter.ROMFS_HEADER
        encoded_len = self._encode_uint(len(data))
        if (len(encoded_kind) + len(encoded_len) + len(data)) & 1:
            encoded_len = b"\x80" + encoded_len
        data = encoded_kind + encoded_len + data
        return data

    def opendir(self, dirname):
        self._dir_stack.append((dirname, bytearray()))

    def closedir(self):
        dirname, dirdata = self._dir_stack.pop()
        dirdata = self._encode_uint(len(dirname)) + bytes(dirname, "utf-8") + dirdata
        self._extend(self._pack(VfsRomWriter.ROMFS_RECORD_KIND_DIRECTORY, dirdata))

    def mkdata(self, data):
        assert len(self._dir_stack) == 1
        return self._extend(self._pack(VfsRomWriter.ROMFS_RECORD_KIND_DATA_VERBATIM, data)) - len(
            data
        )

    def mkfile(self, filename, filedata):
        filename = bytes(filename, "utf-8")
        payload = self._encode_uint(len(filename))
        payload += filename
        if isinstance(filedata, tuple):
            sub_payload = self._encode_uint(filedata[0])
            sub_payload += self._encode_uint(filedata[1])
            payload += self._pack(VfsRomWriter.ROMFS_RECORD_KIND_DATA_POINTER, sub_payload)
        else:
            payload += self._pack(VfsRomWriter.ROMFS_RECORD_KIND_DATA_VERBATIM, filedata)
        self._dir_stack[-1][1].extend(self._pack(VfsRomWriter.ROMFS_RECORD_KIND_FILE, payload))

    async def copy_in()

    def copy_recursively(self, src_dir):
        DIR = 1 << 14
        mpy_cross_missed = 0
        dir_contents = sorted(os.listdir(src_dir))
        for name in dir_contents:
            src_name = src_dir / name
            st = os.stat(src_name)

            if st[0] & DIR:
                # A directory, enter it and copy its contents recursively.
                self.opendir(name)
                await self.copy_recursively(src_name)
                vfs.closedir()
            else:
                # A file.
                did_mpy = False
                name_extra = ""
                if self.cross and name.endswith(".py"):
                    name_mpy = name[:-3] + ".mpy"
                    src_name_mpy = src_dir / name_mpy
                    if not os.path.isfile(src_name_mpy):
                        if mpy_cross_run is not None:
                            did_mpy = True
                            mpy_cross_run(src_name)
                if did_mpy:
                    name = name_mpy
                    src_name = src_name_mpy
                with open(src_name, "rb") as src:
                    self.mkfile(name, src.read())


async def make_romfs(src:anyio.Path, mpy_cross):
    vfs = VfsRomWriter()

    # Build the filesystem recursively.
    await copy_recursively(vfs, src, mpy_cross)
    return vfs.finalise()
