"""
Tests for :class:`~moat.lib.rpc.ListenerLink` and the
:class:`~moat.lib.stream.ReliableMsg` persist-reconnection path.

The listener adapter presents a :class:`~moat.lib.rpc.BaseConnIter` as a
single reconnectable stream: each (re-)entry hands the next incoming
connection to the stack above.  On top of that, a ``ReliableMsg`` layer
with ``persist=True`` rides out transport drops and resumes the session
(retransmitting as needed) when the peer reconnects.
"""

from __future__ import annotations

import anyio
import pytest

from moat.util import attrdict
from moat.lib.codec import get_codec
from moat.lib.micro import TaskGroup
from moat.lib.rpc import BaseConnIter, ListenerLink, TcpIter
from moat.lib.stream import CBORMsgBlk, CBORMsgBuf, ReliableMsg
from moat.src.test import raises

from typing import Self

pytestmark = pytest.mark.anyio

HOST = "127.0.0.1"


class FakeConn:
    """A minimal in-memory stream: ``snd``/``rcv`` blocks and ``rd``/``wr`` bytes.

    Instances are paired via :meth:`pair`.  :meth:`drop` severs the
    transport: subsequent reads and writes on both sides fail with
    ``EOFError`` — the signal ``ReliableMsg`` interprets as "transport
    gone".
    """

    def __init__(self) -> None:
        self.rx: list[bytes] = []
        self.evt = anyio.Event()
        self.peer: FakeConn | None = None
        self.dropped = False

    @classmethod
    def pair(cls) -> tuple[FakeConn, FakeConn]:
        "Create a connected pair."
        a, b = cls(), cls()
        a.peer, b.peer = b, a
        return a, b

    def drop(self) -> None:
        "Sever the transport; wakes the peer with EOFError."
        self.dropped = True
        if (peer := self.peer) is not None:
            peer.dropped = True
            peer.evt.set()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc) -> None:
        pass

    async def snd(self, m) -> None:
        "Enqueue a block for the peer."
        await self.wr(m)

    async def rcv(self) -> bytes:
        "Await the next block from the peer."
        buf = bytearray(4096)
        n = await self.rd(buf)
        return bytes(buf[:n])

    async def wr(self, data) -> int:
        "Enqueue bytes for the peer."
        if self.dropped or self.peer is None:
            raise EOFError
        self.peer.rx.append(bytes(data))
        self.peer.evt.set()
        return len(data)

    async def rd(self, buf) -> int:
        "Fill @buf from queued bytes; EOF when dropped and empty."
        while True:
            if self.rx:
                blk = self.rx[0]
                n = min(len(blk), len(buf))
                buf[:n] = blk[:n]
                if n < len(blk):
                    self.rx[0] = blk[n:]
                else:
                    self.rx.pop(0)
                return n
            if self.dropped:
                raise EOFError
            await self.evt.wait()
            self.evt = anyio.Event()


class ScriptedIter(BaseConnIter):
    """A scripted :class:`BaseConnIter` handing out pre-made connections.

    The test pushes each upcoming transport in advance (:meth:`push`);
    the accept task forwards them to whoever iterates.  This decouples
    "which transports exist" from "when the stack asks for them".
    """

    def __init__(self) -> None:
        super().__init__()
        self.port = -1  # no port to assign; don't block on _port_ready
        self.queue: list[FakeConn] = []
        self.new = anyio.Event()
        self.exited = anyio.Event()

    def push(self, conn: FakeConn) -> None:
        "Queue the next connection to be accepted."
        self.queue.append(conn)
        self.new.set()

    async def accept(self) -> None:
        "Hand out queued connections, one per add_conn call."
        while True:
            if self.queue:
                conn = self.queue.pop(0)
                try:
                    await self.add_conn(conn)
                except BaseException:
                    # Teardown raced the handoff: put the connection back
                    # so the next accept cycle can offer it again.
                    self.queue.insert(0, conn)
                    raise
            else:
                await self.new.wait()
                self.new = anyio.Event()

    async def __aexit__(self, *exc):
        try:
            return await super().__aexit__(*exc)
        finally:
            self.exited.set()


class FailIter(BaseConnIter):
    """A listener whose accept task dies immediately."""

    def __init__(self) -> None:
        super().__init__()
        self.port = -1

    async def accept(self) -> None:
        "Die immediately: simulates a broken listener."
        raise RuntimeError("listener boom")


async def test_listenerlink_delegation():
    """rd/wr/snd/rcv forward to the current connection; EOF when none."""
    it = ScriptedIter()
    ll = ListenerLink(it)
    a, b = FakeConn.pair()
    it.push(a)

    # No connection yet: the delegated methods report EOF.
    with pytest.raises(EOFError):
        await ll.snd(b"x")
    with pytest.raises(EOFError):
        await ll.rcv()
    with pytest.raises(EOFError):
        await ll.wr(b"x")
    with pytest.raises(EOFError):
        await ll.rd(bytearray(4))

    async with ll:
        # Entering pulled the connection: delegation works.
        await ll.snd(b"hello")
        assert await b.rcv() == b"hello"
        await b.snd(b"hi")
        assert await ll.rcv() == b"hi"

        # rd/wr share the same underlying connection.
        await ll.wr(b"bytes")
        assert await b.rcv() == b"bytes"
        await b.snd(b"more")
        buf = bytearray(4)
        assert await ll.rd(buf) == 4
        assert bytes(buf) == b"more"

        # Dropping the transport surfaces as EOFError through the adapter.
        a.drop()
        with pytest.raises(EOFError):
            await ll.rcv()


async def test_listenerlink_next_conn_on_reenter():
    """Re-entering the ListenerLink pulls the *next* queued connection."""
    it = ScriptedIter()
    ll = ListenerLink(it)
    a, pa = FakeConn.pair()
    b, pb = FakeConn.pair()

    it.push(a)
    async with ll:
        await ll.snd(b"one")
        assert await pa.rcv() == b"one"
        a.drop()

    it.push(b)
    async with ll:
        await ll.snd(b"two")
        assert await pb.rcv() == b"two"


async def test_listenerlink_aenter_failure_no_leak():
    """An __aenter__ failure must tear the listener down, not leak it."""
    it = ScriptedIter()

    class FailingSetup(ListenerLink):
        "A stack element whose setup explodes on entry."

        async def setup(self) -> None:
            raise RuntimeError("boom")

    ll = FailingSetup(it)

    with pytest.raises(RuntimeError, match="boom"):
        async with ll:
            pass  # pragma: no cover

    # The listener's accept task must have been torn down with it.
    assert it.exited.is_set()


async def test_listenerlink_accept_crash_propagates():
    """A crashing accept task must propagate out of the context."""
    ll = ListenerLink(FailIter())

    with raises(RuntimeError):
        async with ll:
            await anyio.sleep_forever()


REL_CFG = dict(window=4, timeout=100, retries=999, persist=True, _nowait=True)
"Standard ReliableMsg test parameters."


def _stack(it: ScriptedIter, **kw) -> ReliableMsg:
    """ReliableMsg over a CBOR codec over a scripted iter."""
    return ReliableMsg(CBORMsgBlk(ListenerLink(it), attrdict()), attrdict(REL_CFG, **kw))


def _listeners(stack: ReliableMsg) -> ScriptedIter:
    "The scripted iter beneath a ReliableMsg › CBOR › ListenerLink stack."
    return stack.link.link.listener


async def test_reliable_persist_reconnect_resumes_session():
    """A persisted ReliableMsg survives a transport drop and resumes.

    Both sides run persistent ``ReliableMsg`` stacks over scripted
    transports.  Mid-session the transport is severed; new transports are
    supplied, and the interrupted exchange completes — including
    retransmission of whatever was in flight when the link died.
    """
    srv = _stack(ScriptedIter())
    cli = _stack(ScriptedIter())
    si, ci = _listeners(srv), _listeners(cli)

    # First transport pair.
    s1, c1 = FakeConn.pair()
    si.push(s1)
    ci.push(c1)

    got = []
    n_msgs = 20

    all_got = anyio.Event()

    async def receiver():
        for _ in range(n_msgs):
            got.append(await cli.recv())
        all_got.set()

    async with TaskGroup() as tg, srv, cli:
        await tg.spawn(receiver)

        # Session comes up: the first messages flow.
        for n in range(5):
            await srv.send(dict(n=n))

        # Sever the transport mid-flight, then provision a new one.
        # (Pushing immediately is safe: a cancellation racing the
        # handoff re-queues the connection.)
        s1.drop()
        s2, c2 = FakeConn.pair()
        si.push(s2)
        ci.push(c2)

        # Complete the exchange after the drop.
        for n in range(5, n_msgs):
            await srv.send(dict(n=n))

        with anyio.fail_after(10):
            await all_got.wait()

    assert [m["n"] for m in got] == list(range(n_msgs))


async def test_reliable_persist_survives_multiple_drops():
    """Repeated transport drops still converge thanks to persistence."""
    srv = _stack(ScriptedIter())
    cli = _stack(ScriptedIter())
    si, ci = _listeners(srv), _listeners(cli)

    s_cur, c_cur = FakeConn.pair()
    si.push(s_cur)
    ci.push(c_cur)

    got = []
    n_msgs = 30

    all_got = anyio.Event()

    async def receiver():
        for _ in range(n_msgs):
            got.append(await cli.recv())
        all_got.set()

    async with TaskGroup() as tg, srv, cli:
        await tg.spawn(receiver)

        for n in range(n_msgs):
            await srv.send(dict(n=n))
            if n in (3, 9, 17):
                # Sever and re-provision the transport.
                s_cur.drop()
                s_cur, c_cur = FakeConn.pair()
                si.push(s_cur)
                ci.push(c_cur)

        with anyio.fail_after(10):
            await all_got.wait()

    assert sorted(m["n"] for m in got) == list(range(n_msgs))


async def test_reliable_no_persist_raises_on_drop():
    """Without persist, a transport drop tears the ReliableMsg stack down.

    A read-side drop alone is absorbed (the reader cancels its task
    group); the failure surfaces when the writer next touches the dead
    transport.  The post-drop send runs in its own task because the
    sender's reply event is failed with `ChannelClosed` as the stack
    dismantles itself.
    """
    srv = _stack(ScriptedIter(), persist=False)
    cli = _stack(ScriptedIter(), persist=False)
    si, ci = _listeners(srv), _listeners(cli)

    s1, c1 = FakeConn.pair()
    si.push(s1)
    ci.push(c1)

    with raises(EOFError, OSError):
        async with TaskGroup() as tg, srv, cli:
            await srv.send(dict(n=0))
            assert await cli.recv() == dict(n=0)
            s1.drop()
            # Kick the writer: transmitting on the dead transport is the
            # fatal error that dismantles a non-persistent stack.
            tg.start_soon(srv.send, dict(n=1))
            await anyio.sleep(0.5)

    # The stack is dead and reports so.
    assert srv.closed


async def test_tcpiter_real_socket_smoke():
    """Smoke-test a real TcpIter beneath a ListenerLink.

    One real TCP connection is served through the adapter; a message
    round-trips through a CBOR stack built on top.
    """
    ti = TcpIter(HOST, 0)
    ll = ListenerLink(ti)
    stack = CBORMsgBuf(ll, attrdict())
    codec = get_codec("std-cbor")

    async with TaskGroup() as tg:

        async def connector():
            # TcpIter signals readiness once its port is bound.
            await ti.is_ready()
            stream = await anyio.connect_tcp(HOST, ti.port)
            async with stream:
                await stream.send(codec.encode("hello-there"))
                # Incrementally decode the response.
                while True:
                    data = await stream.receive()
                    codec.feed(memoryview(data))
                    try:
                        resp = next(codec)
                    except StopIteration:
                        continue
                    assert resp == "bye"
                    # Acknowledge so the server can close without racing
                    # our unread reply (avoiding a TCP reset).
                    await stream.send(codec.encode("ack"))
                    return

        tg.start_soon(connector)
        # Entering the stack enters the whole chain below it (codec →
        # ListenerLink → TcpIter); the layers must not be entered
        # individually.
        async with stack:
            msg = await stack.recv()
            assert msg == "hello-there"
            await stack.send("bye")
            # Wait for the acknowledgement before tearing the link down.
            assert await stack.recv() == "ack"
