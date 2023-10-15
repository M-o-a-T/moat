"""
Stream link-up support for MoaT commands
"""

from __future__ import annotations

import sys

from moat.util import ValueEvent, obj2name, NotGiven
from .util import ValueTask, SendIter, RecvIter, StoppedError
from moat.micro.compat import CancelledError, WouldBlock, log, Lock, ACM, AC_use, AC_exit, shield, TaskGroup
from moat.micro.proto.stack import RemoteError, SilentRemoteError, BaseMsg

from .base import BaseCmd

class BaseBBMCmd(BaseCmd):
    """
    This is a command handler that connects MoaT's Cmd tree to a `BaseBuf`,
    `BaseBlk` or `BaseMsg` instance.

    Override `setup` to return that instance.
    """
    def __init__(self, cfg):
        super().__init__(cfg)
        self.w_lock = Lock()

    async def setup(self):
        raise NotImplementedError("setup", self.path)

    async def run(self):
        ACM(self)
        try:
            self.dev = await self.setup()
            await super().run()
        finally:
            del self.dev
            await AC_exit(self)
    
    async def cmd_rd(self, n=64):
        """read some data"""
        b = bytearray(n)
        r = await self.dev.rd(b)
        if r == n:
            return b
        elif r <= n>>2:
            return bytes(b[:r])
        else:
            b = memoryview(b)
            return b[:r]

    async def cmd_wr(self, b):
        """write some data"""
        async with self.w_lock:
            await self.dev.wr(b)

    async def cmd_crd(self, n=64):
        """read some console data"""
        b = bytearray(n)
        r = await self.dev.crd(b)
        if r == n:
            return b
        elif r <= n>>2:
            return bytes(b[:r])
        else:
            b = memoryview(b)
            return b[:r]

    async def cmd_cwr(self, b):
        """write some console data"""
        async with self.w_lock:
            await self.dev.cwr(b)

    async def cmd_s(self, m):
        """send a message"""
        return await self.dev.send(m)

    async def cmd_r(self):
        """receive a message"""
        return await self.dev.recv(m)



class BaseCmdMsg(BaseCmd):
    """
    This is a command handler that relays messages between MoaT's Cmd tree
    and a `BaseMsg` stream.
    """
    tg:TaskGroup = None

    def __init__(self, cfg):
        super().__init__(cfg)
        self.reply = {}
        self.seq = 2
        # locally-generated seqnums must be even
        # also we want them to not be zero
        # TODO: CBOR: use negative seqnums for replies
        #            instead of flipping the bottom bit

    async def stream(self) -> BaseMsg:
        """
        Creates the actual data stream.

        Must be overridden.
        """
        raise NotImplementedError("Create the stream: ",self.__class__.__name__)

    async def task(self):
        """
        Start the stack.

        You typically override `stream`, not this method.
        """
        err = None
        try:
            await AC_use(self, self._cleanup_open_commands)
            self.s = await self.stream()
            async with TaskGroup() as self.tg:
                self.set_ready()
                while True:
                    msg = await self.s.recv()
                    await self._handle(msg)
#       except (EOFError,OSError,SilentRemoteError) as exc:
#           err = exc
#           raise
#       except Exception as exc:
#           err = exc
#           log("Run", err=err)
#           raise
#       except BaseException as exc:
#           err = exc
#           raise
        finally:
            self.s = None

    # stacked
    async def error(self, exc):
        print("ERROR: " + repr(error), file=sys.stderr)

    def _cleanup_open_commands(self):
        for e in self.reply.values():
            e.cancel()

    async def reply_result(self, i, res):
        if i is None:
            return
        try:
            await self.s.send({'i':i, 'd':res})
        except Exception as e:
            await self.reply_error(i, e)
        except BaseException as e:
            await self.reply_error(i, e)
            raise

    async def reply_error(self, i, exc, x=()):
        """
        Reply to message #@i with an error.

        Exception types in @x are expected and will not be logged.
        """
        res = NotGiven
        try:
            if isinstance(exc, SilentRemoteError):
                pass
            elif x and isinstance(exc, tuple(x)):
                pass
            else:
                log("ERROR handling %d", i, err=exc)
            if i is None:
                return
            res = {'i': i}
            if isinstance(exc,Exception):
                try:
                    obj2name(type(exc))
                except KeyError:
                    res["e"] = "E:" + repr(exc)
                else:
                    res["e"] = type(exc)
                    res["d"] = exc.args
            else:
                res["e"] = StoppedError
                res["d"] = (repr(exc),)
            await self.s.send(res)
        except TypeError as e2:
            log("ERROR returning %r", res, err=e2)
            await self.s.send({'e': "T:" + repr(e2), 'i': i})

    async def _handle(self, msg):
        """
        Main handler for incoming messages
        """
        if not isinstance(msg, dict):
            print("?3", msg, file=sys.stderr)
            return
        a = msg.get("a", None)
        i = msg.get("i", None)
        d = msg.get("d", NotGiven)
        e = msg.get("e", None)
        r = msg.get("r", None)
        n = msg.get("n", None)
        x = msg.get("x", ())

        if i is not None:
            i ^= 1

        for k in msg.keys():
            if k not in "aidrenx":
                log("Unknown %s: %r", k, msg)
                break

        if a is not None:
            # incoming request
            # runs in a separate task
            # XXX create a task pool?
            if d is NotGiven:
                d = None
            if r is None:
                t = ValueTask(self, i, x, self.root.dispatch, a, d, x_err=x)
            else:
                t = SendIter(self, i, r, a, d)

            if i is not None:
                if i in self.reply:
                    log("msgid known?!? %d", i)
                    tt = self.reply.pop(i)
                    tt.i = None
                    tt.error(RuntimeError("OldCmd"))
                self.reply[i] = t
            rm = await t.start(self.tg)
            if r is not None:
                await self.s.send({'i':i, 'r':rm})

        else:
            # reply
            if i is None:
                log("?? %r", msg)
                return

            t = self.reply.get(i, None)
            if t is None:
                log("unknown %r", msg)
                return

            if e is not None:
                if isinstance(e,type):
                    if d is NotGiven:
                        d = ()
                    e = e(*d)
                elif isinstance(e,str):
                    e = RemoteError(e)
                elif isinstance(e,Exception):
                    pass
                else:
                    log("unknown err %r", msg)
                    e = StoppedError()
                t.set_error(e)

            elif r is not None:
                if r is False:
                    t.error(StopIter())
                    del self.reply[i]
                else:
                    t.set_r(r)

            elif d is not NotGiven:
                if isinstance(t, (SendIter,RecvIter)):
                    if n:
                        t.set(d,n=n)
                    else:
                        t.set(d)
                    return
                else:
                    t.set(d)
                    del self.reply[i]

            else: # just i
                t.cancel()
                del self.reply[i]


    async def dispatch(self, action, msg=None, rep:int=None, wait=True, x_err=()):  # pylint:disable=arguments-differ
        """
        Forward a request to the remote side, return the response.

        The message is either the second parameter, or a dict (use any
        number of keywords).

        If @wait is False, the message doesn't have a sequence number and
        thus no reply will be expected.

        @rep requests iterated replies.
        """

        if len(action) == 1:
            a=action[0]
            if a[0] == "!":
                return await super().dispatch((a,),msg, rep=rep,wait=wait,x_err=x_err)

        if await self.wait_ready():
            raise StoppedError  # already down

        if not wait:
            msg = {"a": action, "d": msg}
            await self.s.send(msg)
            return
        
        # Find a small-ish but unique *even* seqnum
        # even seqnums are requests from the other side
        if self.seq > 10 * (len(self.reply) + 5):
            self.seq = 10
        while True:
            self.seq += 2
            seq = self.seq
            if seq not in self.reply:
                break
        msg = {"a": action, "d": msg, "i": seq}
        if x_err:
            msg["x"] = x_err

        if rep:
            msg["r"] = rep
            self.reply[seq] = e = RecvIter(rep)
            await self.s.send(msg)
            res = await e.get()
            if res is not None:
                log("Spurious IterReply %r", res)
            return e
        else:
            self.reply[seq] = e = ValueEvent()
            try:
                await self.s.send(msg)
                return await e.get()
            finally:
                self.reply.pop(seq, None)

class CmdMsg(BaseCmdMsg):
    """
    A baseCmdMsg with a ready-made link that it opens.
    """
    def __init__(self, link, cfg):
        super().__init__(cfg)
        self.link = link

    def stream(self) -> Awaitable[BaseMsg]:
        return AC_use(self, self.link)

class SingleCmdMsg(BaseCmdMsg):
    """
    A BaseCmdMsg that disconnects on error, or when the connection ends,
    without propagating the exception.
    """
    async def run(self):
        try:
            await super().run()
        except (EOFError, OSError, SilentRemoteError) as exc:
            log("Err %s: %r", self.path, repr(exc))
        except Exception as exc:
            log("Err %s", self.path, err=exc)


class ExtCmdMsg(SingleCmdMsg):
    """SingleCmdMsg, on a stream that was established externally.

    The caller is responsible for calling `wait_stopped`
    and then closing the stream!
    """
    def __init__(self, stream:BaseMsg, cfg={}):
        super().__init__(cfg)
        self.__s = stream

    async def stream(self):
        return await AC_use(self, self.__s)

