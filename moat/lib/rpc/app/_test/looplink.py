"""
Bi- or multidirectional loopback app.
"""

from __future__ import annotations

import anyio

from moat.lib.rpc import BaseCmd
from moat.lib.rpc.stream.cmdbbm import BaseCmdBBM

from typing import TYPE_CHECKING  # isort:skip

if TYPE_CHECKING:
    from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream

    from moat.lib.rpc import SubMsgSender

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

    remote: SubMsgSender

    q_wm: MemoryObjectSendStream[Any]
    q_wmr: MemoryObjectReceiveStream[Any]
    q_wb: MemoryObjectSendStream[bytes]
    q_wbr: MemoryObjectReceiveStream[bytes]
    q_ws: bytearray
    q_wse: anyio.Event
    q_wc: bytearray
    q_wce: anyio.Event

    q_rmw: MemoryObjectSendStream[Any]
    q_rm: MemoryObjectReceiveStream[Any]
    q_rbw: MemoryObjectSendStream[bytes]
    q_rb: MemoryObjectReceiveStream[bytes]
    q_rse: anyio.Event
    q_rs: bytearray
    q_rce: anyio.Event
    q_rc: bytearray

    async def setup(self):
        """Set up the queues based on usage config."""
        p = self.cfg.get("path", None)
        if isinstance(p, str):
            raise TypeError(f"Need a path, not {p!r}")
        if p is not None:
            self.remote = self.root.sub_at(p)

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
        try:
            return self.q_wm.send(m)
        except AttributeError:
            return self.remote.xs(m=m)

    doc_xs = dict(_d="q write remote", _0="any:msg")

    def cmd_xs(self, m) -> Awaitable[None]:
        """Remotely write the message read queue."""
        return self.q_rmw.send(m)

    doc_r = dict(_d="q read", _r="any:msg")

    def cmd_r(self) -> Awaitable[Any]:
        """Read the message queue."""
        try:
            return self.q_rm.receive()
        except AttributeError:
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
        try:
            return self.q_wb.send(m)
        except AttributeError:
            return self.remote.xsb(m=m)

    doc_xsb = dict(_d="b write remote", _r="bytes:msg")

    def cmd_xsb(self, m) -> Awaitable[None]:
        """Remotely write the block read queue."""
        return self.q_rbw.send(m)

    doc_rb = dict(_d="b read ", _0="bytes:msg")

    def cmd_rb(self) -> Awaitable[bytes]:
        """Read the byte queue."""
        try:
            return self.q_rb.receive()
        except AttributeError:
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
        try:
            q_wse = self.q_wse
        except AttributeError:
            return await self.remote.xwr(b)
        else:
            self.q_ws.extend(b)
            q_wse.set()
            self.q_wse = anyio.Event()

    doc_xwr = dict(_d="s write remote", _0="bytes:stream")

    async def cmd_xwr(self, b) -> None:
        """Remotely write the byte read queue."""
        self.q_rs.extend(b)
        self.q_rse.set()
        self.q_rse = anyio.Event()

    doc_rd = dict(_d="s read", _r="bytes:stream", _0="int:len(64)")

    async def cmd_rd(self, n=64) -> bytes:
        """Read the byte queue."""
        try:
            while not self.q_rs:
                await self.q_rse.wait()
        except AttributeError:
            return await self.remote.xrd(n=n)
        else:
            n = min(n, len(self.q_rs))
            res = bytes(self.q_rs[:n])
            self.q_rs[:n] = b""
            return res

    doc_xrd = dict(_d="s read remote", _r="bytes:stream", _0="int:len(64)")

    async def cmd_xrd(self, n=64) -> bytes:
        """Remotely read the byte write queue."""
        q_ws = self.q_ws
        while not q_ws:
            await self.q_wse.wait()
            if self.q_wse is None:
                raise RuntimeError("No write queue")
        n = min(n, len(q_ws))
        res = bytes(q_ws[:n])
        q_ws[:n] = b""
        return res

    doc_rw = BaseCmdBBM.doc_rw
    stream_rw = BaseCmdBBM.stream_rw

    # Console

    doc_cwr = dict(_d="s write cons", _0="bytes:stream")

    async def cmd_cwr(self, b) -> None:
        """Write to the console queue."""
        try:
            self.q_wc.extend(b)
        except AttributeError:
            return await self.remote.xcwr(b)
        else:
            self.q_wce.set()
            self.q_wce = anyio.Event()

    doc_xcwr = dict(_d="s write remote cons", _0="bytes:stream")

    async def cmd_xcwr(self, b) -> None:
        """Remotely write the console read queue."""
        self.q_rc.extend(b)
        self.q_rce.set()
        self.q_rce = anyio.Event()

    doc_crd = dict(_d="s read cons", _r="bytes:stream", _0="int:len(64)")

    async def cmd_crd(self, n=64) -> bytes:
        """Read the console queue."""
        try:
            while not self.q_rc:
                await self.q_rce.wait()
        except AttributeError:
            return await self.remote.xcrd(n=n)
        else:
            q_rc = self.q_rc
            n = min(n, len(q_rc))
            res = bytes(q_rc[:n])
            q_rc[:n] = b""
            return res

    doc_xcrd = dict(_d="s read remote cons", _r="bytes:stream", _0="int:len(64)")

    async def cmd_xcrd(self, n=64) -> bytes:
        """Remotely read the console write queue."""
        while not self.q_wc:
            await self.q_wce.wait()
        q_wc = self.q_wc
        n = min(n, len(q_wc))
        res = bytes(q_wc[:n])
        q_wc[:n] = b""
        return res

    doc_crw = BaseCmdBBM.doc_crw
    stream_crw = BaseCmdBBM.stream_crw
