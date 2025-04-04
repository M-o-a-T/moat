"""
Message streaming.
"""
from __future__ import annotations
from contextlib import asynccontextmanager
from moat.util import Path, QueueFull
from moat.micro.compat import Queue, log, L, TaskGroup
from functools import partial
from moat.lib.cmd.base import MsgLink, MsgHandler
from moat.lib.cmd.const import *
from moat.lib.cmd.errors import ShortCommandError
from moat.lib.cmd.msg import Msg

import logging
logger=logging.getLogger(__name__)

class StreamHandler(MsgHandler):
    """
    This class transforms handler requests into streamed messages.

    This is a sans-I/O class. Usage:

    * open an async context on the ``StreamHandler`` instance
    * start a task that reads your external source and feeds the result
      to `msg_in`
    * start a task that loops on `msg_out` and sends the result

    You can use the `start` method to run these task within the context's
    internal taskgroup. They will be auto-cancelled when leaving the
    context.
    """
    def __init__(self, handler: MsgHandler):
        self._msgs: dict[int, StreamLink] = {}
        self._send_q = Queue(9)
        self._recv_q = Queue(99)
        self._handler = handler

        self._id1 = set()
        if L:
            self._id2 = set()
        self._id3 = set()
        self._id = 0

    @property
    def is_idle(self) -> bool:
        if self._msgs:
            return False
        if self._send_q.qsize():
            return False
        if self._recv_q.qsize():
            return False
        return True

    async def handle(self, msg:Msg, rcmd:list):
        """
        Forward a new message to the other side.
        """
        if not rcmd:
            raise ShortCommandError
        if rcmd[-1] == "!l":
            rcmd.pop()
            return await super().handle(msg,rcmd)

        i = self._gen_id()
        link = StreamLink(self, i)
        log("NEWID1 %d %d",i, id(link))
        msg.replace_with(link)
        self.attach(link)
        args = [msg.cmd]
        args.extend(msg.args)
        self.send(link, args, msg._kw, B_STREAM if msg.can_stream else 0)
        if not msg.can_stream:
            msg.set_end()
        # breakpoint()  # fwd

    def _gen_id(self):
        # Generate the next free ID.
        if self._id1:
            return self._id1.pop()
        if L and self._id2:
            return self._id2.pop()
        if self._id3:
            return self._id3.pop()
        self._id += 1
        return self._id

    def msg_in(self, msg:list) -> None:
        """process an incoming message"""
        i = msg[0]
        flag = i&3
        # flip sign
        i = -1 - (i >> 2)

        a = msg[1:]
        kw = a.pop() if a and isinstance(a[-1],dict) else {}

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
                rem = Msg.Call(cmd,a,kw,flag)
                link = StreamLink(self, i)
                log("NEWID2 %d %d",i,id(link))
                rem.replace_with(link)
                if not stream:
                    link.set_end()
                self.attach(link)
                self._tg.start_soon(self._handle, msg, link)
        else:
            try:
                link.ml_send(a,kw,flag)
            except EOFError:
                try:
                    self.send(link, [E_NO_STREAM], None, B_ERROR)
                except EOFError:
                    pass
                self.detach(link)
            except QueueFull:
                if flag&B_STREAM:
                    self.send(link, [E_SKIP], None, B_ERROR|B_STREAM)
                else:
                    self.send(link, [E_SKIP], None, B_ERROR)
                    self.detach(link)

            else:
                if link.end_both:
                    self.detach(link)

    async def _handle(self, msg:list, link:StreamLink):
        if self._handler is None:
            # intentionally not async here, as that may end up
            # in a deadlock
            self.send(link, [E_NO_CMD], None, B_ERROR)
            return

        rem=link.remote
        try:
            await self._handler.handle(rem, rem.rcmd)
            if not link.end_both:
                breakpoint() # link closed
                raise RuntimeError("Link was not closed")
        except Exception as exc:
            log("Error handling %r: %r", msg, exc)
            logger.exception("Error handling %r: %r", msg, exc)
            self.send(link, (exc.__class__.__name__,)+exc.args, None, B_ERROR)
        except BaseException as exc:
            log("Error handling %r: %r", msg, exc)
            logger.exception("Error handling %r: %r", msg, exc)
            self.send(link, (exc.__class__.__name__,)+exc.args, None, B_ERROR)
            raise

    def attach(self, proc:StreamLink):
        """
        Attach a handler for incoming messages.
        """
        if proc.id in self._msgs:
            raise ValueError(f"MID {mid} already known")
        self._msgs[proc.id] = proc

    def detach(self, link:StreamLink):
        """
        Remove a handler for raw incoming messages.
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


    def send(self, link:StreamLink, a:list, kw:dict, flag:int) -> Awaitable[None]:
        assert isinstance(a, (list, tuple)), a
        assert 0 <= flag <= 3, flag
        self._send_q.put_nowait((link, a, kw, flag))

    async def msg_out(self) -> list:
        link, a, kw, flag = await self._send_q.get()
        i = (link.id<<2) | flag

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
            res.extend({})

        return res

    def start(self, cmd, *a, **kw):
        if kw:
            self._tg.start_soon(partial(cmd,*a,*kw))
        else:
            self._tg.start_soon(cmd,*a)

    @asynccontextmanager
    async def _ctx(self) -> Self:
        async with TaskGroup() as tg:
            self._tg = tg
            try:
                yield self
            finally:
                for link in list(self._msgs.values()):
                    if not link.end_there:
                        try:
                            self.send(link, [E_CANCEL], None, B_ERROR)
                        except Exception:
                            pass
                    link.kill()
                tg.cancel()

        for link in list(self._msgs.values()):
            self.detach(link)


class StreamLink(MsgLink):
    """This is the handler for messages that forwards them to the stream."""
    def __init__(self, handler:StreamHandler, id:int):
        super().__init__()
        self.__handler = handler
        self.id = id

    def ml_recv(self, a:list, kw:dict, flags:int) -> None:
        """data to be forwarded across the link"""
        assert 0 <= flags <= 3, flags
        log("LR %d %r %r %d",self.id,a,kw,flags)
        self.__handler.send(self, a,kw,flags)

    def ml_send(self, a:list, kw:dict, flags:int) -> None:
        """data to be forwarded to our remote"""
        log("LS %d %r %r %d",self.id,a,kw,flags)
        assert 0 <= flags <= 3, flags
        super().ml_send(a,kw,flags)

    def stream_detach(self):
        self.__handler.detach(self)
