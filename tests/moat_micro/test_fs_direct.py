"""
Basic file system test, using commands directly
"""

from __future__ import annotations

import anyio
import pytest

from moat.lib.path import P
from moat.lib.rpc._test import rpc_stack

pytestmark = pytest.mark.anyio

# pylint:disable=R0801 # Similar lines in 2 files

CFG = """
app: dir
r:
  app: _test.MpyCmd
  cfg:
    app:
      app: dir
      f:
        app: fs.Cmd
        root: "/tmp/nonexisting"
      r:
        app: stdio.StdIO
        link: &link
          frame: 0x85
          console: false
        log:
          txt: "S"
  link: *link
"""


async def test_fuse(tmp_path):
    "file system test"
    p = anyio.Path(tmp_path) / "fuse"
    r = anyio.Path(tmp_path) / "root"
    async with rpc_stack(tmp_path, CFG, {"r": {"cfg": {"app": {"f": {"root": str(r)}}}}}) as d:
        await p.mkdir()
        async with d.sub_at(P("r.f")) as w:
            await w.new(p="test")
            f = await w.open(p="test", m="w")
            n = await w.wr(f=f, d="Fubar\n")
            await w.cl(f=f)
            assert n == 6
        st = await (r / "test").stat()
        assert st.st_size == n


async def test_stream_rd(tmp_path):
    "stream-read a file"
    r = anyio.Path(tmp_path) / "root"
    async with (
        rpc_stack(tmp_path, CFG, {"r": {"cfg": {"app": {"f": {"root": str(r)}}}}}) as d,
        d.sub_at(P("r.f")) as w,
    ):
        # Create a file with known content
        await w.new(p="stream_test")
        f = await w.open(p="stream_test", m="w")
        await w.wr(f=f, d=b"Hello streaming world!\n" * 10)
        await w.cl(f=f)

        # Stream-read the file: open, stream rd, close.
        f = await w.open(p="stream_test", m="r")
        chunks = []
        async with w.cmd(P("rd"), f, n=16).stream_in() as st:
            async for m in st:
                chunks.append(m[0])
        await w.cl(f=f)

        data = b"".join(chunks)
        assert data == b"Hello streaming world!\n" * 10


async def test_stream_wr(tmp_path):
    "stream-write a file"
    r = anyio.Path(tmp_path) / "root"
    async with (
        rpc_stack(tmp_path, CFG, {"r": {"cfg": {"app": {"f": {"root": str(r)}}}}}) as d,
        d.sub_at(P("r.f")) as w,
    ):
        # Stream-write a file: open, stream wr, close.
        payload = b"Written via streaming.\n" * 5
        f = await w.open(p="sw_test", m="w")
        async with w.cmd(P("wr"), f).stream_out() as st:
            # Send in two chunks
            mid = len(payload) // 2
            await st.send(payload[:mid])
            await st.send(payload[mid:])
        await w.cl(f=f)

        # Verify by reading back
        f = await w.open(p="sw_test", m="r")
        data = b""
        while True:
            chunk = await w.rd(f=f, o=len(data), n=64)
            if not chunk:
                break
            data += chunk
        await w.cl(f=f)
        assert data == payload


@pytest.mark.xfail(reason="RPC streaming protocol bug: server-side stream_in misses chunks")
async def test_stream_wr_offset(tmp_path):
    "stream-write a file at a nonzero offset"
    r = anyio.Path(tmp_path) / "root"
    async with (
        rpc_stack(tmp_path, CFG, {"r": {"cfg": {"app": {"f": {"root": str(r)}}}}}) as d,
        d.sub_at(P("r.f")) as w,
    ):
        # Write initial content
        await w.new(p="ofs_test")
        f = await w.open(p="ofs_test", m="w")
        await w.wr(f=f, d=b"AAAAABBBB")
        await w.cl(f=f)

        # Overwrite bytes at offset 5 via streaming.
        # Use "r+" to avoid truncating the file.
        f = await w.open(p="ofs_test", m="r+")
        async with w.cmd(P("wr"), f, 5).stream_out() as st:
            await st.send(b"CDEF")
        await w.cl(f=f)

        # Verify
        f = await w.open(p="ofs_test", m="r")
        data = b""
        while True:
            chunk = await w.rd(f=f, o=len(data), n=64)
            if not chunk:
                break
            data += chunk
        await w.cl(f=f)
        assert data == b"AAAAACDEF"


async def test_stream_rd_offset(tmp_path):
    "stream-read a file from a nonzero offset"
    r = anyio.Path(tmp_path) / "root"
    async with (
        rpc_stack(tmp_path, CFG, {"r": {"cfg": {"app": {"f": {"root": str(r)}}}}}) as d,
        d.sub_at(P("r.f")) as w,
    ):
        # Create a file with known content
        await w.new(p="rofs_test")
        f = await w.open(p="rofs_test", m="w")
        await w.wr(f=f, d=b"0123456789ABCDEF")
        await w.cl(f=f)

        # Stream-read from offset 8
        f = await w.open(p="rofs_test", m="r")
        chunks = []
        async with w.cmd(P("rd"), f, 8, n=4).stream_in() as st:
            async for m in st:
                chunks.append(m[0])
        await w.cl(f=f)

        data = b"".join(chunks)
        assert data == b"89ABCDEF"
