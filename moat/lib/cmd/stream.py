"""
Message streaming.
"""

from __future__ import annotations
from contextlib import asynccontextmanager
from moat.util import Path, QueueFull
from moat.util.compat import Queue, log, L, TaskGroup
from functools import partial
from moat.lib.cmd.base import MsgLink, MsgHandler
from moat.lib.cmd.const import *
from moat.lib.cmd.errors import ShortCommandError
from moat.lib.cmd.msg import Msg, log_exc

def i_f2wire(id: int, flag: int) -> int:
    assert id != 0
    assert 0 <= flag <= 3
    if id > 0:
        id -= 1
    return (id << 2) | flag


def wire2i_f(id: int) -> tuple[int, int]:
    f = id & 3
    id >>= 2
    if id >= 0:
        id += 1
    return id, f


class HandlerStream(MsgHandler):
    """
    This class bidirectionally translates MsgHandler calls to streamed messages.

    This is a sans-I/O class. Usage:

    * open an async context on an instance of this class
    * start a task that reads your external source and feeds the result
      to `msg_in`.
    * start a task that loops on `msg_out` and sends the result. It should
      terminate on `EOFError` from `msg_out`.

    You can use the `start` method to run these tasks (and any others you
    might need) within the context's internal taskgroup. They will be
    auto-cancelled when leaving the context.

    Message encoding:

    This class encodes messages as plain Python lists. They consist of
    integers plus any other data type your payload consists of.

    Error handling uses proxies or strings for the error name, but it will
    send a plain error indication if it can't encode its data. If your
    messages contain keywords, the codec needs to support dicts.

    """

    _tg: TaskGroup = None
    _id = 0

    def __init__(self, handler: MsgSender | None):
        self._msgs: dict[int, StreamLink] = {}
        self._send_q = Queue(9)
        self._recv_q = Queue(99)
        self._handler = handler

        self._id1: set[int] = set()
        if L:
            self._id2: set[int] = set()
        self._id3: set[int] = set()

    @property
    def is_idle(self) -> bool:
        if self._msgs:
            return False
        if self._send_q.qsize():
            return False
        if self._recv_q.qsize():
            return False
        return True

    async def handle(self, msg: Msg, rcmd: list) -> None:
        """
        Forward a new message to the other side.
        """
        if not rcmd:
            raise ShortCommandError
        if rcmd[-1] == "!l":
            rcmd.pop()
            return await super().handle(msg, rcmd)

        rcmd.reverse()
        i = self._gen_id()
        can_stream = msg.can_stream
        link = StreamLink(self, i)
        msg.replace_with(link)
        self.attach(link)
        args = [rcmd]
        args.extend(msg.args)
        await self.send(link, args, msg._kw, B_STREAM if can_stream else 0)
        if not can_stream:
            msg.set_end()
        # breakpoint()  # fwd

    def _gen_id(self) -> int:
        # Generate the next free ID.
        if self._id1:
            return self._id1.pop()
        if L and self._id2:
            return self._id2.pop()
        if self._id3:
            return self._id3.pop()
        self._id += 1
        return self._id

    async def closed_input(self) -> None:
        """
        Input is down, no more messages
        """
        if self._tg is not None:
            self._tg.cancel_scope.cancel()
            self._send_q.close_sender()
        for link in list(self._msgs.values()):
            link.kill()


    async def msg_in(self, msg: list) -> None:
        """process an incoming message"""
        i, flag = wire2i_f(msg[0])
        # flip sign
        i = -i

        a = msg[1:]
        kw = a.pop() if a and isinstance(a[-1], dict) else {}

        stream = flag & B_STREAM
        error = flag & B_ERROR

        try:
            link = self._msgs[i]

        except KeyError:
            if i > 0:
                log("Spurious message %r", msg)
            elif error:
                log("Spurious error %r", msg)
            else:
                # assemble the message
                cmd = a.pop(0) if a else Path()
                rem = Msg.Call(cmd, a, kw, flag)
                link = StreamLink(self, i)
                rem.replace_with(link)
                if not stream:
                    link.set_end()
                self.attach(link)
                if link.remote.cmd is None:
                    breakpoint()  # CMD
                self._tg.start_soon(self._handle, msg, link)
        else:
            try:
                await link.ml_send(a, kw, flag)
            except EOFError:
                try:
                    await self.send(link, [E_NO_STREAM], None, B_ERROR)
                except EOFError:
                    pass
                self.detach(link)
            except QueueFull:
                if flag & B_STREAM:
                    await self.send(link, [E_SKIP], None, B_ERROR | B_STREAM)
                else:
                    await self.send(link, [E_SKIP], None, B_ERROR)
                    self.detach(link)

            else:
                if link.end_both:
                    self.detach(link)

    async def _handle(self, msg: list, link: StreamLink) -> None:
        if self._handler is None:
            # intentionally not async here, as that may end up
            # in a deadlock
            await self.send(link, [E_NO_CMD], None, B_ERROR)
            return

        rem = link.remote
        try:
            res = await self._handler.handle(rem, rem.rcmd)
            if res is not None:
                if link.end_there:
                    raise ValueError(f"Already ended but returned {res!r}")
                else:
                    await link.remote.ml_send([res], None, 0)
        except Exception as exc:
            log_exc(exc,"Error %r: %r", msg, exc)
            if link.remote is not None:
                await link.remote.ml_send_error(exc)
        except BaseException as exc:
            if link.remote is not None:
                await link.remote.ml_send_error(exc)
            raise
        else:
            # may have been replaced by the handler
            if rem is link.remote and not rem.end_here:
                await self.send(link, [None], None, 0)

        if not link.end_both:
            log("NotClosed L%d L%d", link.link_id, link.remote.link_id if link.remote else -1)
            # breakpoint() # notclosed
            pass  # raise RuntimeError("Link was not closed")

    def attach(self, proc: StreamLink) -> None:
        """
        Attach a link.
        """
        if proc.id in self._msgs:
            raise ValueError(f"MID {mid} already known")
        self._msgs[proc.id] = proc

    def detach(self, link: StreamLink) -> None:
        """
        Remove a link.
        """
        mid = link.id
        if self._msgs.get(mid) is not link:
            # already removed
            return
        del self._msgs[mid]
        if mid <= 0:  # remote
            return

        # Optimizing for CBOR integers
        if mid < 6:
            self._id1.add(mid)
        elif L and mid < 64:
            self._id2.add(mid)
        else:
            self._id3.add(mid)

    async def send(self, link: StreamLink, a: list, kw: dict, flag: int) -> None:
        assert isinstance(a, (list, tuple)), a
        assert 0 <= flag <= 3, flag
        log("SendQ L%d %r %r %d", link.link_id, a, kw, flag)
        await self._send_q.put((link, a, kw, flag))

    async def msg_out(self) -> list:
        link, a, kw, flag = await self._send_q.get()
        i = i_f2wire(link.id, flag)

        # Handle last-arg-is-dict ambiguity
        if kw:
            pass
        elif not a or not isinstance(a[-1], dict):
            kw = None
        elif kw is None:
            kw = {}
        res = [i]
        res.extend(a)
        if kw is not None:
            res.append(kw)
        elif a and isinstance(a[-1], dict):
            res.append({})

        return res

    def start(self, cmd, *a, **kw) -> None:
        if kw:
            self._tg.start_soon(partial(cmd, *a, *kw))
        else:
            self._tg.start_soon(cmd, *a)

    @asynccontextmanager
    async def _ctx(self) -> Self:
        async with TaskGroup() as tg:
            self._tg = tg
            try:
                yield self
            finally:
                self._send_q.close_sender()
                self._recv_q.close_sender()
                for link in list(self._msgs.values()):
                    link.kill()

                tg.cancel()

        for link in list(self._msgs.values()):
            self.detach(link)


class StreamLink(MsgLink):
    """This is the handler for messages that forwards them to the stream."""

    def __init__(self, stream: Stream, id: int):
        super().__init__()
        self.__stream = stream
        self.id = id

    async def ml_recv(self, a: list, kw: dict, flags: int) -> None:
        """data to be forwarded across the link"""
        assert 0 <= flags <= 3, flags
        log("LR L%d %d %r %r %d", self.link_id, self.id, a, kw, flags)
        await self.__stream.send(self, a, kw, flags)

    async def ml_send(self, a: list, kw: dict, flags: int) -> None:
        """data to be forwarded to our remote"""
        log("LS L%d %d %r %r %d", self.link_id, self.id, a, kw, flags)
        assert 0 <= flags <= 3, flags
        await super().ml_send(a, kw, flags)

    def stream_detach(self) -> None:
        self.__stream.detach(self)
