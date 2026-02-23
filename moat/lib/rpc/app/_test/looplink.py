"""
Bi- or multidirectional loopback app.
"""

from __future__ import annotations

import anyio

from moat.lib.rpc import BaseCmd
from moat.lib.rpc.stream.cmdbbm import BaseCmdBBM

from typing import TYPE_CHECKING  # isort:skip

if TYPE_CHECKING:
    from collections.abc import Awaitable
    from typing import Any


class LoopLink(BaseCmd):
    """Bi- or even multidirectional loopback.

    The ``path`` config says where to read from.
    If not given, uses the local read buffer.
    Read relationships do NOT need to be symmetrical.
    Reading from self works.

    ``usage`` is a string that controls which buffers to create.

    * m – Messages
    * b – Byte blocks
    * s – serial data
    * c – Console stream

    Lower case are write buffers; upper case are read buffers.
    If the remote side is a LoopBBM, both are required.

    Requests use a queue if it exists. Otherwise the request is forwarded
    to the external end of the remote queue.
    """

    # q_ATX.
    # A: r=read_side w=write_side
    # T: see docstring
    # X: back end: r=read w=write e=event

    # write queues.

    doc = dict(
        _c=dict(
            _d="Loopback test (data)",
            qlen="int:len of queues",
            usage="str:what to forward",
        )
    )

    q_wm, q_wmr = None, None
    q_wb, q_wbr = None, None
    q_ws, q_wse = None, None
    q_wc, q_wce = None, None

    # read queues
    q_rmw, q_rm = None, None
    q_rbw, q_rb = None, None
    q_rse, q_rs = None, None
    q_rce, q_rc = None, None

    async def setup(self):
        """Set up the queues based on usage config."""
        p = self.cfg.get("path", None)
        if isinstance(p, str):
            raise TypeError(f"Need a path, not {p!r}")
        self.remote = self.root.sub_at(p) if p is not None else None

        u = self.cfg.get("usage", "")
        if "m" in u:
            self.q_wm, self.q_wmr = anyio.create_memory_object_stream(self.cfg.get("qlen", 99))
        if "b" in u:
            self.q_wb, self.q_wbr = anyio.create_memory_object_stream(self.cfg.get("qlen", 99))
        if "s" in u:
            self.q_ws, self.q_wse = bytearray(), anyio.Event()
        if "c" in u:
            self.q_wc, self.q_wce = bytearray(), anyio.Event()

        if "M" in u:
            self.q_rmw, self.q_rm = anyio.create_memory_object_stream(self.cfg.get("qlen", 99))
        if "B" in u:
            self.q_rbw, self.q_rb = anyio.create_memory_object_stream(self.cfg.get("qlen", 99))
        if "S" in u:
            self.q_rse, self.q_rs = anyio.Event(), bytearray()
        if "C" in u:
            self.q_rce, self.q_rc = anyio.Event(), bytearray()

        await super().setup()

    # Messages

    doc_s = dict(_d="q write", _0="any:msg")

    def cmd_s(self, m) -> Awaitable[None]:
        """Write to the message queue."""
        if self.q_wm:
            return self.q_wm.send(m)
        else:
            return self.remote.xs(m=m)

    doc_xs = dict(_d="q write remote", _0="any:msg")

    def cmd_xs(self, m) -> Awaitable[None]:
        """Remotely write the message read queue."""
        return self.q_rmw.send(m)

    doc_r = dict(_d="q read", _r="any:msg")

    def cmd_r(self) -> Awaitable[Any]:
        """Read the message queue."""
        if self.q_rm:
            return self.q_rm.receive()
        else:
            return self.remote.xr()

    doc_xr = dict(_d="q read remote", _r="any:msg")

    def cmd_xr(self) -> Awaitable[Any]:
        """Remotely read the message write queue."""
        return self.q_wmr.receive()

    doc_mrw = BaseCmdBBM.doc_mrw
    stream_mrw = BaseCmdBBM.stream_mrw

    # Blocks

    doc_sb = dict(_d="b write ", _r="bytes:msg")

    def cmd_sb(self, m) -> Awaitable[None]:
        """Write to the block queue."""
        if self.q_wb:
            return self.q_wb.send(m)
        else:
            return self.remote.xsb(m=m)

    doc_xsb = dict(_d="b write remote", _r="bytes:msg")

    def cmd_xsb(self, m) -> Awaitable[None]:
        """Remotely write the block read queue."""
        return self.q_rbw.send(m)

    doc_rb = dict(_d="b read ", _0="bytes:msg")

    def cmd_rb(self) -> Awaitable[bytes]:
        """Read the byte queue."""
        if self.q_rb:
            return self.q_rb.receive()
        else:
            return self.remote.xrb()

    doc_xrb = dict(_d="b read remote", _0="bytes:msg")

    def cmd_xrb(self) -> Awaitable[bytes]:
        """Remotely read the block write queue."""
        return self.q_wbr.receive()

    doc_brw = BaseCmdBBM.doc_brw
    stream_brw = BaseCmdBBM.stream_brw

    # Bytes

    doc_wr = dict(_d="s write", _0="bytes:stream")

    async def cmd_wr(self, b) -> None:
        """Write to the byte queue."""
        if self.q_wse is not None:
            self.q_ws.extend(b)
            self.q_wse.set()
            self.q_wse = anyio.Event()
        else:
            return await self.remote.xwr(b)

    doc_xwr = dict(_d="s write remote", _0="bytes:stream")

    async def cmd_xwr(self, b) -> None:
        """Remotely write the byte read queue."""
        self.q_rs.extend(b)
        self.q_rse.set()
        self.q_rse = anyio.Event()

    doc_rd = dict(_d="s read", _r="bytes:stream", _0="int:len(64)")

    async def cmd_rd(self, n=64) -> bytes:
        """Read the byte queue."""
        if self.q_rse is None:
            return await self.remote.xrd(n=n)
        while not self.q_rs:
            await self.q_rse.wait()
        n = min(n, len(self.q_rs))
        res = self.q_rs[:n]
        self.q_rs[:n] = b""
        return res

    doc_xrd = dict(_d="s read remote", _r="bytes:stream", _0="int:len(64)")

    async def cmd_xrd(self, n=64) -> bytes:
        """Remotely read the byte write queue."""
        while not self.q_ws:
            await self.q_wse.wait()
        n = min(n, len(self.q_ws))
        res = self.q_ws[:n]
        self.q_ws[:n] = b""
        return res

    doc_rw = BaseCmdBBM.doc_rw
    stream_rw = BaseCmdBBM.stream_rw

    # Console

    doc_cwr = dict(_d="s write cons", _0="bytes:stream")

    async def cmd_cwr(self, b) -> None:
        """Write to the console queue."""
        if self.q_wce is not None:
            self.q_wc.extend(b)
            self.q_wce.set()
            self.q_wce = anyio.Event()
        else:
            return await self.remote.xcwr(b)

    doc_xcwr = dict(_d="s write remote cons", _0="bytes:stream")

    async def cmd_xcwr(self, b) -> None:
        """Remotely write the console read queue."""
        self.q_rc.extend(b)
        self.q_rce.set()
        self.q_rce = anyio.Event()

    doc_crd = dict(_d="s read cons", _r="bytes:stream", _0="int:len(64)")

    async def cmd_crd(self, n=64) -> bytes:
        """Read the console queue."""
        if self.q_rce is None:
            return await self.remote.xcrd(n=n)
        while not self.q_rc:
            await self.q_rce.wait()
        n = min(n, len(self.q_rc))
        res = self.q_rc[:n]
        self.q_rc[:n] = b""
        return res

    doc_xcrd = dict(_d="s read remote cons", _r="bytes:stream", _0="int:len(64)")

    async def cmd_xcrd(self, n=64) -> bytes:
        """Remotely read the console write queue."""
        while not self.q_wc:
            await self.q_wce.wait()
        n = min(n, len(self.q_wc))
        res = self.q_wc[:n]
        self.q_wc[:n] = b""
        return res

    doc_crw = BaseCmdBBM.doc_crw
    stream_crw = BaseCmdBBM.stream_crw
