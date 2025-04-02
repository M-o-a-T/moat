"""
Message streaming.
"""
from __future__ import annotations
from moat.util import Path
from functools import partial

class StreamHandler(MsgEndpoint):
    """
    This class transforms handler requests into streamed messages.

    This is a sans-I/O class. You need to provide

    * an async context on your `StreamHandler` instance
    * a task that reads your external source and feeds the result
      to `msg_in`
    * a task that loops on `msg_out` and sends the result

    You can use `start` to run these task within the context's taskgroup.
    """
    def __init__(self, handler: MsgEndpoint):
        self._msgs: dict[int, StreamRemote] = {}
        self._send_q = Queue(9)
        self._recv_q = Queue(99)
        self._debug = logger.warning
        self._handler = handler

        self._id1 = set()
        if L:
            self._id2 = set()
        self._id3 = set()
        self._id = 0

    async def handle(self, msg:Msg, rcmd:list):
        if not rcmd:
            raise ShortCommandError
        if rcmd[-1] == "!l":
            rcmd.pop()
            await super().handle()


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
        a = msg[1:]
        kw = a.pop() if a and isinstance(a[-1],dict) else {}

        # stream = i & B_STREAM
        error = flag & B_ERROR
        i = -1 - (i >> 2)
        if i >= 0:
            i += 1
        try:
            conv = self._msgs[i]

        except KeyError:
            if i > 0:
                self._debug("Spurious message %r", msg)
            elif error:
                self._debug("Spurious error %r", msg)
            else:
                # assemble the message
                cmd = a.pop(0) if a else Path()
                msg = Msg.Call(cmd,a,kw)
                conv = StreamRemote(self, i)
                if not stream:
                    conv.sd_end |= SD_IN
                msg.emplace(conv)
                self.attach(i,conv)
                self._tg.start_soon(self._handle, msg, i)
        else:
            if not stream:
                conv.sd_end |= SD_IN
                if conv.sd_end == SD_BOTH:
                    self.detach(i,conv)
            try:
                conv.ml_send(a,kw,flag)
            except EOFError:
                self.detach(i,conv)
                try:
                    self.send((i << 2) | B_ERROR, [E_NO_STREAM])
                except EOFError:
                    pass
            except QueueFullError:
                if flag&B_STREAM:
                    self.send((i << 2) | B_ERROR|B_STREAM, [E_SKIP])
                else:
                    self.detach(i,conv)
                    self.send((i << 2) | B_ERROR, [E_SKIP])

    async def _handle(self, msg, i):
            elif self._handler is None:
                if i > 0:
                    i -= 1
                # intentionally not async here, as that may end up
                # in a deadlock
                self.send((i << 2) | B_ERROR, [E_NO_CMD])
        try:
            await self._handler(msg)
        except Exception as exc:
            log("Error handling %r", msg)
        except BaseException as exc:
            log("Error handling %r", msg)
            raise
        finally:
            self.detach(i)

    def attach(self, mid:int, proc:StreamRemote):
        """
        Attach a handler for incoming messages.
        """
        if not force and mid in self._msgs:
            raise ValueError(f"MID {mid} already known")
        self._msgs[mid] = proc

    def detach(self, mid:int, proc=None):
        """
        Remove a handler for raw incoming messages.
        """
        if proc is not None and self._msgs[mid] is not proc:
            # already superseded
            return
        try:
            del self._msgs[mid]
        except KeyError:
            if mid > 0:
                raise
        if mid <= 0:  # remote
            return

        # Optimizing for CBOR integers
        if mid < 6:
            self._id1.add(mid)
        elif L and mid < 64:
            self._id2.add(mid)
        else:
            self._id3.add(mid)


    def send(self, i:int, a:list, kw:dict, flag:int) -> Awaitable[None]:
        assert isinstance(a, (list, tuple)), a
        assert isinstance(i, int), i
        assert 0 <= flag <= 3, flag
        assert not i&3, i
        i |= flag
        if not (flag&B_STREAM):
            conv.sd_end |= SD_OUT
            if conv.sd_end == SD_BOTH:
                self.detach(i>>2,conv)
        return self._send_q.put_nowait((i, a, kw))

    async def msg_out(self) -> list:
        i, a, kw = await self._send_q.get()

        # Handle last-arg-is-dict ambiguity
        if not kw is None and a and isinstance(a[-1], dict):
            kw = {}
        res = [i]
        res.extend(a)
        if kw:
            res.append(kw)
        elif a and isinstance(a[-1], dict):
            res.extend({})
        return res

    def start(self, cmd, *a, **kw):
        if kw:
            self._tg.start(partial(cmd,*a,*kw))
        else:
            self._tg.start(cmd,*a)

    @asynccontextmanager
    async def _ctx(self) -> Self:
        async with TaskGroup() as tg:
            self._tg = tg
            try:
                yield self
            finally:
                for conv in list(self._msgs.values()):
                    conv(None)
                tg.cancel()

        for k in list(self._msgs.keys()):
            self.detach(k)


class StreamRemote(MsgRemote):
    sd_end:int=SD_NONE

    def __init__(self, handler:StreamHandler, id:int):
        super().__init__()
        self._handler = handler
        self._id = id

    def ml_recv(self, a:list, kw:dict, flags:int) -> None:
        """data to be forwarded across the link"""
        assert 0 <= flags <= 3, flags
        if not (flags&B_STREAM):
            self.sd_end |= SD_OUT
        self._handler.send(self._id|flags, a,kw)

