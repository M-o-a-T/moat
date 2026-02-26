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
        if p is None:
            self.remote = None
        else:
            root = self.root
            if root is None:
                raise RuntimeError("Not attached")
            self.remote = root.sub_at(p)

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
            remote = self.remote
            if remote is None:
                raise RuntimeError("No remote")
            return remote.xs(m=m)

    doc_xs = dict(_d="q write remote", _0="any:msg")

    def cmd_xs(self, m) -> Awaitable[None]:
        """Remotely write the message read queue."""
        q = self.q_rmw
        if q is None:
            raise RuntimeError("No read queue")
        return q.send(m)

    doc_r = dict(_d="q read", _r="any:msg")

    def cmd_r(self) -> Awaitable[Any]:
        """Read the message queue."""
        if self.q_rm:
            return self.q_rm.receive()
        else:
            remote = self.remote
            if remote is None:
                raise RuntimeError("No remote")
            return remote.xr()

    doc_xr = dict(_d="q read remote", _r="any:msg")

    def cmd_xr(self) -> Awaitable[Any]:
        """Remotely read the message write queue."""
        q = self.q_wmr
        if q is None:
            raise RuntimeError("No write queue")
        return q.receive()

    doc_mrw = BaseCmdBBM.doc_mrw
    stream_mrw = BaseCmdBBM.stream_mrw

    # Blocks

    doc_sb = dict(_d="b write ", _r="bytes:msg")

    def cmd_sb(self, m) -> Awaitable[None]:
        """Write to the block queue."""
        if self.q_wb:
            return self.q_wb.send(m)
        else:
            remote = self.remote
            if remote is None:
                raise RuntimeError("No remote")
            return remote.xsb(m=m)

    doc_xsb = dict(_d="b write remote", _r="bytes:msg")

    def cmd_xsb(self, m) -> Awaitable[None]:
        """Remotely write the block read queue."""
        q = self.q_rbw
        if q is None:
            raise RuntimeError("No read queue")
        return q.send(m)

    doc_rb = dict(_d="b read ", _0="bytes:msg")

    def cmd_rb(self) -> Awaitable[bytes]:
        """Read the byte queue."""
        if self.q_rb:
            return self.q_rb.receive()
        else:
            remote = self.remote
            if remote is None:
                raise RuntimeError("No remote")
            return remote.xrb()

    doc_xrb = dict(_d="b read remote", _0="bytes:msg")

    def cmd_xrb(self) -> Awaitable[bytes]:
        """Remotely read the block write queue."""
        q = self.q_wbr
        if q is None:
            raise RuntimeError("No write queue")
        return q.receive()

    doc_brw = BaseCmdBBM.doc_brw
    stream_brw = BaseCmdBBM.stream_brw

    # Bytes

    doc_wr = dict(_d="s write", _0="bytes:stream")

    async def cmd_wr(self, b) -> None:
        """Write to the byte queue."""
        if self.q_wse is not None:
            q_ws = self.q_ws
            q_wse = self.q_wse
            if q_ws is None or q_wse is None:
                raise RuntimeError("No write queue")
            q_ws.extend(b)
            q_wse.set()
            self.q_wse = anyio.Event()
        else:
            remote = self.remote
            if remote is None:
                raise RuntimeError("No remote")
            return await remote.xwr(b)

    doc_xwr = dict(_d="s write remote", _0="bytes:stream")

    async def cmd_xwr(self, b) -> None:
        """Remotely write the byte read queue."""
        q_rs = self.q_rs
        q_rse = self.q_rse
        if q_rs is None or q_rse is None:
            raise RuntimeError("No read queue")
        q_rs.extend(b)
        q_rse.set()
        self.q_rse = anyio.Event()

    doc_rd = dict(_d="s read", _r="bytes:stream", _0="int:len(64)")

    async def cmd_rd(self, n=64) -> bytes:
        """Read the byte queue."""
        if self.q_rse is None:
            remote = self.remote
            if remote is None:
                raise RuntimeError("No remote")
            return await remote.xrd(n=n)
        q_rse = self.q_rse
        q_rs = self.q_rs
        if q_rse is None or q_rs is None:
            raise RuntimeError("No read queue")
        while not q_rs:
            await q_rse.wait()
            q_rse = self.q_rse
            if q_rse is None:
                raise RuntimeError("No read queue")
        n = min(n, len(q_rs))
        res = bytes(q_rs[:n])
        q_rs[:n] = b""
        return res

    doc_xrd = dict(_d="s read remote", _r="bytes:stream", _0="int:len(64)")

    async def cmd_xrd(self, n=64) -> bytes:
        """Remotely read the byte write queue."""
        q_ws = self.q_ws
        q_wse = self.q_wse
        if q_ws is None or q_wse is None:
            raise RuntimeError("No write queue")
        while not q_ws:
            await q_wse.wait()
            q_wse = self.q_wse
            if q_wse is None:
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
        if self.q_wce is not None:
            q_wc = self.q_wc
            q_wce = self.q_wce
            if q_wc is None or q_wce is None:
                raise RuntimeError("No write queue")
            q_wc.extend(b)
            q_wce.set()
            self.q_wce = anyio.Event()
        else:
            remote = self.remote
            if remote is None:
                raise RuntimeError("No remote")
            return await remote.xcwr(b)

    doc_xcwr = dict(_d="s write remote cons", _0="bytes:stream")

    async def cmd_xcwr(self, b) -> None:
        """Remotely write the console read queue."""
        q_rc = self.q_rc
        q_rce = self.q_rce
        if q_rc is None or q_rce is None:
            raise RuntimeError("No read queue")
        q_rc.extend(b)
        q_rce.set()
        self.q_rce = anyio.Event()

    doc_crd = dict(_d="s read cons", _r="bytes:stream", _0="int:len(64)")

    async def cmd_crd(self, n=64) -> bytes:
        """Read the console queue."""
        if self.q_rce is None:
            remote = self.remote
            if remote is None:
                raise RuntimeError("No remote")
            return await remote.xcrd(n=n)
        q_rce = self.q_rce
        q_rc = self.q_rc
        if q_rce is None or q_rc is None:
            raise RuntimeError("No read queue")
        while not q_rc:
            await q_rce.wait()
            q_rce = self.q_rce
            if q_rce is None:
                raise RuntimeError("No read queue")
        n = min(n, len(q_rc))
        res = bytes(q_rc[:n])
        q_rc[:n] = b""
        return res

    doc_xcrd = dict(_d="s read remote cons", _r="bytes:stream", _0="int:len(64)")

    async def cmd_xcrd(self, n=64) -> bytes:
        """Remotely read the console write queue."""
        q_wc = self.q_wc
        q_wce = self.q_wce
        if q_wc is None or q_wce is None:
            raise RuntimeError("No write queue")
        while not q_wc:
            await q_wce.wait()
            q_wce = self.q_wce
            if q_wce is None:
                raise RuntimeError("No write queue")
        n = min(n, len(q_wc))
        res = bytes(q_wc[:n])
        q_wc[:n] = b""
        return res

    doc_crw = BaseCmdBBM.doc_crw
    stream_crw = BaseCmdBBM.stream_crw
    remote: SubMsgSender | None = None

    q_wm: MemoryObjectSendStream[Any] | None
    q_wmr: MemoryObjectReceiveStream[Any] | None
    q_wb: MemoryObjectSendStream[bytes] | None
    q_wbr: MemoryObjectReceiveStream[bytes] | None
    q_ws: bytearray | None
    q_wse: anyio.Event | None
    q_wc: bytearray | None
    q_wce: anyio.Event | None

    q_rmw: MemoryObjectSendStream[Any] | None
    q_rm: MemoryObjectReceiveStream[Any] | None
    q_rbw: MemoryObjectSendStream[bytes] | None
    q_rb: MemoryObjectReceiveStream[bytes] | None
    q_rse: anyio.Event | None
    q_rs: bytearray | None
    q_rce: anyio.Event | None
    q_rc: bytearray | None
