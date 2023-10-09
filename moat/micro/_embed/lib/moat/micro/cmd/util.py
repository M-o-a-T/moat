"""
Helpers for MoaT command interpreters et al.
"""

from __future__ import annotations

from moat.util import ValueEvent, as_proxy, NotGiven

from moat.micro.compat import ticks_diff, ticks_ms, sleep_ms, log
from moat.micro.proto.stack import RemoteError, SilentRemoteError

StopIter = StopAsyncIteration

as_proxy("_KyErr", KeyError, replace=True)
as_proxy("_AtErr", AttributeError, replace=True)
as_proxy("_NiErr", NotImplementedError, replace=True)
as_proxy("_RemErr", RemoteError, replace=True)
as_proxy("_SRemErr", SilentRemoteError, replace=True)

as_proxy("_StpIter", StopIter, replace=True)

@as_proxy("_StpErr")
class StoppedError(Exception):
    pass

async def run_no_exc(p,msg):
    try:
        r = p(**msg)
        if hasattr(r, "throw"):  # coroutine
            r = await r
    except Exception as err:
        log("Error in %r %r",p,msg, _err=err)

def get_part(cur, p):
    import sys
    print("GP",cur,p, file=sys.stderr)
    for pp in p:
        try:
            cur = getattr(cur,pp)
        except (TypeError,AttributeError):
            cur = cur[pp]
    return cur

def set_part(cur, p, v):
    cur = get_part(cur,p[:-1])
    try:
        cur[p[-1]] = v
    except TypeError:
        setattr(cur, p[-1], v)


def enc_part(cur):
    """
    Helper method to encode a larger dict/list partially.

    The result is either some object that's not a dict or list, or a
    (X,L) tuple where X is the dict/list in question except with all the
    complex parts removed, and L is a list of keys/offsets with complex
    data to retrieve
    """
    def _complex(v):
        if isinstance(v, (dict, list, tuple)):
            return True
        return False

    if isinstance(cur, dict):
        c = {}
        s = []
        for k, v in cur.items():
            if _complex(v):
                s.append(k)
            else:
                c[k] = v
        if s:
            return c, s
        else:
            # dict has no complex values: return directly
            return c

    elif isinstance(cur, (list, tuple)):
        c = []
        s = []
        for k, v in enumerate(cur):
            if _complex(v):
                c.append(None)
                s.append(k)
            else:
                c.append(v)
        # cannot do a direct return here
        return c, s

    else:
        return cur
        # guaranteed not to be a tuple


class ValueTask:
    """
    An object that forwards a task's return value.
    """
    def __init__(self, cmd, i, p, *a, **k):
        self.cmd = cmd
        self.i = i
        self.p = p
        self.a = a
        self.k = k
        self._t = None
    
    async def start(self):
        if self._t is not None:
            raise RuntimeError("dup")
        self._t = await self.cmd._tg.spawn(self._wrap, _name="Val")
                       
    async def _wrap(self):
        try:
            err = None
            res = await self.p(*self.a,**self.k)
        except Exception as exc:
            err = exc
        except BaseException as exc:
            err = StoppedError(repr(exc))
            raise                
        finally:
            if err is None:
                await self.cmd.reply_result(self.i, res)
            else:
                await self.cmd.reply_error(self.i, err)

    def cancel(self):
        if self._t is not None:
            self._t.cancel()
            self._t = False


class IterWrap:
    """
    An iterator that repeatedly calls a function.

    Set @ival to the initial value.
    """
    def __init__(self, p,a=(),k={}, ival=NotGiven):
        self.p = p
        self.a = a
        self.k = k
        self.ival = ival

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.ival is NotGiven:
            r =  self.p(*self.a,**self.k)
            if hasattr(r, "throw"):  # coroutine
                r = await r
        else:
            r,self.ival = self.ival,NotGiven
        return r


class SendIter(ValueTask):
    """
    The sender of outgoing iterated messages.

    It implements a task that iterates the source and forwards the data.

    When the task ends, a cancellation message is sent to the remote side.
    """
    def __init__(self, cmd, i, r, a, d):
        self.r = r
        self.ac = a
        self.ad = d
        super().__init__(cmd, i, self._run)

    async def _run(self):
        try:
            cnt = 1
            async with self.cmd.root.dispatch(self.ac, self.ad, rep=self.r) as self.it:
                async for msg in self.it:
                    await self.cmd.parent.send({'i':self.i, 'd':msg, 'n': cnt})
                    cnt += 1
        finally:
            self.it = None

    async def set(self, msg):
        await self.it.set(msg)


class _DelayedIter:
    pass

class DelayedIter(_DelayedIter):
    """
    An iterator that delays calling the wrapped iterator.
    """
    def __init__(self, t:int, it:Iterator):
        self.it = it
        self.t = t
        self._next = ticks_add(ticks_ms(), -t)

        self._warned = 2
        # warns on the second, fifth, ninth excessive delay
        # don't warn on the first call: starting the iterator
        # might take some extra time

    def __aiter__(self):
        return self

    async def __anext__(self):
        t = ticks_ms()
        td = ticks_diff(self._next, t)
        if td > -10:  # add some slack
            self._next = ticks_add(self._next, self.t)
            if td > 0:
                await sleep_ms(td)
        else:
            # This took too long. Reset.
            self._warned += 1
            if not self.warned & (self.warned-1):
                # if power of two
                log("IterDelay %r %d", -td)
            self._next = ticks_add(t, self.t)
        return await self.it.__anext__()


class RecvIter(_DelayedIter):
    """
    The recipient of incoming iterated messages.

    It implements an iterator protocol and forwards them to its reader.
    """

    def __init__(self, t):
        self.t = t
        self._warned = 1
        self._val = ValueEvent()
        self.cnt = 0

    def __aiter__(self):
        return self

    async def __aexit__(self, *err):
        pass

    async def get(self):
        try:
            return await self._val.get()
        finally:
            if not self._warned:
                # startup is done
                self._warned = 1
            if self._val.is_set():
                self._val = ValueEvent()

    async def __aenter__(self):
        pass

    __anext__ = get

    def set_r(self, t):
        """
        Initial message for iterators
        """
        self.t = t
        self._val.set(None)

    def set(self, val, n=0):
        if self._val.is_set():
            if self._warned:
                self._warned += 1
            if not self._warned & (self._warned-1):
                log("RemIterSoon %r", val)
            if not self._warned:
                return
            self._val = ValueEvent()
        if n > 0:
            if n == self.cnt:
                log(f"dup {n}")
                return
            if n < self.cnt:
                self.cnt = 1
            else:
                self.cnt += 1
            if n > self.cnt:
                log(f"Missed {n-self.cnt}")
                self.cnt = n
        self._val.set(val)

    def error(self, err):
        self._val.set_error(err)
        self._warned = 0

    def cancel(self):
        self._val.set_error(StoppedError("cancel"))
        self._warned = 0

