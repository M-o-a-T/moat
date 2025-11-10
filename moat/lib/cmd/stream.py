"""
Message streaming.
"""

from __future__ import annotations

from functools import partial

from moat.util import Path, QueueFull
from moat.lib.cmd.base import MsgHandler, MsgLink, MsgSender
from moat.lib.cmd.const import (
    B_ERROR,
    B_STREAM,
    E_CANCEL,
    E_ERROR,
    E_NO_CMD,
    E_NO_CMDS,
    E_NO_STREAM,
    E_SKIP,
    E_UNSPEC,
)
from moat.lib.cmd.errors import ShortCommandError
from moat.lib.cmd.msg import Msg, log_exc
from moat.util.compat import (
    ACM,
    AC_exit,
    Event,
    L,
    Queue,
    TaskGroup,
    log,
    shield,
    sleep_ms,
    ticks_diff,
    ticks_ms,
)

from typing import TYPE_CHECKING, cast

try:
    from collections.abc import Iterable, Mapping, Sequence
except ImportError:
    Iterable = object
    Sequence = (list, tuple)
    Mapping = dict

if TYPE_CHECKING:
    from logging import Logger

    from .base import OptDict

    from collections.abc import Sequence
    from typing import Any


def B_FL_NAME(flag):
    "stringify message flags"
    if flag & B_ERROR:
        return ".W" if flag & B_STREAM else ".E"
    else:
        return ".S" if flag & B_STREAM else ""


def B_ERR_NAME(err):
    "stringify message errors"
    if isinstance(err, Exception):
        return repr(err)
    if err >= 0:
        return f"S+{err}"
    if err <= E_NO_CMD:
        return f"NO_CMD_{-E_NO_CMD.value - err}"
    if err == E_UNSPEC:
        return "UNSPEC"
    if err == E_NO_STREAM:
        return "NO_STREAM"
    if err == E_CANCEL:
        return "CANCEL"
    if err == E_NO_CMDS:
        return "NO_CMDS"
    if err == E_SKIP:
        return "SKIP"
    if err == E_ERROR:
        return "ERROR"
    return f"?{err}"


def i_f2wire(id: int, flag: int) -> int:  # noqa: D103
    assert id != 0
    assert 0 <= flag <= 3
    if id > 0:
        id -= 1
    return (id << 2) | flag


def wire2i_f(id: int) -> tuple[int, int]:  # noqa: D103
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

    def __init__(self, sender: MsgSender | None, logger: Logger | None = None):
        self._msgs: dict[int, StreamLink] = {}
        self._send_q = Queue(9)
        self._recv_q = Queue(99)
        self._sender = sender

        self._logger = getattr(logger, "debug", logger)

        self.reader_done = Event()
        self.writer_done = Event()
        self.closing = True

        self._id1: set[int] = set()
        if L:
            self._id2: set[int] = set()
        self._id3: set[int] = set()

    @property
    def is_idle(self) -> bool:  # noqa: D102
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
        if self.closing:
            raise EOFError

        if not rcmd:
            raise ShortCommandError(msg.cmd)
        if rcmd[-1] == "!l":
            rcmd.pop()
            return await super().handle(msg, rcmd)

        rcmd = rcmd[:]
        rcmd.reverse()

        i = self._gen_id()
        can_stream = msg.can_stream
        link = StreamLink(self, i)
        msg.replace_with(link)
        self.attach(link)
        args = [rcmd]
        args.extend(msg.args)
        await self.send(link, args, msg._kw, B_STREAM if can_stream else 0)  # noqa: SLF001
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
        self.closing = True

        if (tg := self._tg) is not None:
            self._tg = None
            self._send_q.close_sender()
            await self.writer_done.wait()
            self._recv_q.close_sender()
            if self._read_task is not None:
                self._read_task.cancel()
                await self.reader_done.wait()

            tg.cancel_scope.cancel()

        for link in list(self._msgs.values()):
            await link.kill()

    async def msg_in(self, msg: list) -> None:
        """process an incoming message"""
        i, flag = wire2i_f(msg[0])
        # flip sign
        i = -i

        if self._logger:
            self._logger(
                "IN : %d%s %s%r",
                i,
                B_FL_NAME(flag),
                B_ERR_NAME(msg[1]) + " " if flag & B_ERROR else "",
                msg[2:] if flag & B_ERROR else msg[1:],
            )

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

                # … and build a stream for it
                link = StreamLink(self, i)
                rem.replace_with(link)
                if not stream:
                    link.set_end()
                self.attach(link)
                link.task = await self._tgs.spawn(self._handle, msg, link)
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
        """
        Task for a new incoming connection.
        """
        if self._sender is None:
            await self.send(link, [E_NO_CMD], None, B_ERROR)
            return
        if self.closing:
            if not link.end_here:
                await self.send(link, [E_CANCEL], None, B_ERROR)
            return

        rem = cast(Msg, link.remote)
        try:
            res = await self._sender.handle(rem, rem.rcmd)
            if res is not None:
                if link.end_there:
                    raise ValueError(f"Already ended but returned {res!r}")
                else:
                    await link.remote.ml_send([res], None, 0)
        except Exception as exc:
            log_exc(exc, "Error %r: %r", msg, exc)
            if link.remote is not None:
                await link.remote.ml_send_error(exc)
        except BaseException as exc:
            if link.remote is not None:
                with shield():
                    await link.remote.ml_send_error(exc)
            raise
        else:
            # may have been replaced by the handler
            if rem is link.remote and not rem.end_here:
                await self.send(link, [None], None, 0)

        if not link.end_both:
            # log("NotClosed L%d L%d", link.link_id, link.remote.link_id if link.remote else -1)
            # breakpoint() # notclosed
            pass  # raise RuntimeError("Link was not closed")

    def attach(self, proc: StreamLink) -> None:
        """
        Attach a link.
        """
        if proc.id in self._msgs:
            raise ValueError(f"MID {proc.id} already known")
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
        if L:
            self._dly_q.put_nowait((mid, ticks_ms()))
        else:
            if mid < 6:
                self._id1.add(mid)
            else:
                self._id3.add(mid)

    async def _dly(self):
        "Delay for message IDs because we don't want to re-use them immediately."
        while True:
            mid, t = await self._dly_q.get()
            tt = ticks_ms()
            td = ticks_diff(tt, t)
            if td < 1000:
                await sleep_ms(1000 - td)
            if mid < 6:
                self._id1.add(mid)
            elif mid < 64:
                self._id2.add(mid)
            else:
                self._id3.add(mid)

    async def send(self, link: StreamLink, a: list, kw: dict, flag: int) -> None:  # noqa: D102
        if self.closing:
            raise EOFError
        assert isinstance(a, (list, tuple)), a
        assert 0 <= flag <= 3, flag
        # log("SendQ L%d %r %r %d", link.link_id, a, kw, flag)
        await self._send_q.put((link, a, kw, flag))

    async def msg_out(self) -> list:  # noqa: D102
        link, a, kw, flag = await self._send_q.get()
        i = i_f2wire(link.id, flag)

        # Handle last-arg-is-dict ambiguity
        if kw:
            pass
        elif not a or not isinstance(a[-1], dict):
            kw = None
        elif kw is None:
            kw = {}
        res: list[Any] = [i]
        res.extend(a)
        if kw is not None:
            res.append(kw)
        elif a and isinstance(a[-1], dict):
            res.append({})

        if self._logger:
            self._logger(
                "OUT: %d%s %s%r",
                link.id,
                B_FL_NAME(flag),
                B_ERR_NAME(res[1]) + " " if flag & B_ERROR else "",
                res[2:] if flag & B_ERROR else res[1:],
            )
        return res

    def start(self, cmd, *a, **kw) -> None:  # noqa: D102
        if kw:
            self._tg.start_soon(partial(cmd, *a, *kw))
        else:
            self._tg.start_soon(cmd, *a)

    async def __aenter__(self):
        acm = ACM(self)
        try:
            tg: TaskGroup = await acm(TaskGroup())
            self._tg = tg
            self._tgs = await acm(TaskGroup())
            self.closing = False

            evt1 = Event()
            evt2 = Event()
            self._read_task = await tg.spawn(self._run_read, evt1)
            self._write_task = await tg.spawn(self._run_write, evt2)
            await evt1.wait()
            await evt2.wait()
            if L:
                self._dly_q = Queue(999)
                await acm(self._dly_q.close_sender)
                tg.start_soon(self._dly)
            return self

        except BaseException as exc:
            await AC_exit(self, type(exc), exc, None)
            raise

    async def _run_read(self, evt):
        try:
            if self.reader_done.is_set():
                self.reader_done = Event()
            evt.set()
            await self.read_stream()
        finally:
            self.reader_done.set()
            self._read_task = None

    async def _run_write(self, evt):
        try:
            if self.writer_done.is_set():
                self.writer_done = Event()
            evt.set()
            await self.write_stream()
        finally:
            self.writer_done.set()
            self._write_task = None

    async def read_stream(self):
        """
        Stream reader.

        Must be overridden: Iterate: call `msg_out` and write its return value.
        """
        raise NotImplementedError

    async def write_stream(self):
        """
        Stream writer.

        Must be overridden: Iterate: read data and call `msg_in` with the result.
        """
        raise NotImplementedError

    async def __aexit__(self, *exc):
        self._tgs.cancel()
        try:
            with shield():
                await self.closed_input()
            self._recv_q.close_sender()
            self._msgs = {}

            with shield():
                for link in list(self._msgs.values()):
                    await link.kill()
            assert not self._msgs

        finally:
            await AC_exit(self, *exc)


class StreamLink(MsgLink):
    """This is the handler for messages that forwards them to the stream."""

    def __init__(self, stream: Msg, id: int):
        super().__init__()
        self.__stream = stream
        self.id = id
        self.task = None

    async def ml_recv(self, a: Sequence, kw: OptDict, flags: int) -> None:
        """data to be forwarded across the link"""
        if self.__stream is None:
            raise EOFError
        assert 0 <= flags <= 3, flags
        # log("LR L%d %d %r %r %d", self.link_id, self.id, a, kw, flags)
        await self.__stream.send(self, a, kw, flags)

    async def ml_send(self, a: Sequence, kw: OptDict, flags: int) -> None:
        """data to be forwarded to our remote"""
        # log("LS L%d %d %r %r %d", self.link_id, self.id, a, kw, flags)
        assert 0 <= flags <= 3, flags
        await super().ml_send(a, kw, flags)

    def stream_detach(self) -> None:  # noqa: D102
        if self.__stream is not None:
            self.__stream.detach(self)
            self.__stream = None
        if self.task is not None:
            try:
                self.task.cancel()
            except RuntimeError:
                pass  # self-cancel on µPy is forbidden
            else:
                self.task = None
