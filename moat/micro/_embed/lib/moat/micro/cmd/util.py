"""
Helpers for MoaT command interpreters et al.
"""

from __future__ import annotations

from moat.util import NotGiven, ValueEvent, as_proxy

from moat.micro.compat import (
    TimeoutError,  # pylint: disable=redefined-builtin
    log,
    sleep_ms,
    ticks_add,
    ticks_diff,
    ticks_ms,
    wait_for_ms,
)
from moat.micro.proto.stack import RemoteError, SilentRemoteError

# Typing

from typing import TYPE_CHECKING  # isort:skip

if TYPE_CHECKING:
    from anyio import CancelScope
    from typing import Any, AsyncIterable, AsyncIterator, Callable, Iterator, Mapping

    from moat.micro.cmd.base import BaseCmd


StopIter = StopAsyncIteration

as_proxy("_KyErr", KeyError, replace=True)
as_proxy("_AtErr", AttributeError, replace=True)
as_proxy("_NiErr", NotImplementedError, replace=True)
as_proxy("_RemErr", RemoteError, replace=True)
as_proxy("_SRemErr", SilentRemoteError, replace=True)

as_proxy("_StpIter", StopIter, replace=True)


@as_proxy("_StpErr")
class StoppedError(Exception):
    "Called command/app is not running"
    pass


async def wait_complain(s: str, i: int, p: Callable, *a, **k):
    "Complain on stderr if waiting too long"
    try:
        await wait_for_ms(i, p, *a, **k)
    except TimeoutError:
        log("Delayed  %s", s)
        await p(*a, **k)
        log("Delay OK %s", s)


async def run_no_exc(p, msg, x_err=()):
    """Call p(msg) but log exceptions"""
    try:
        r = p(**msg)
        if hasattr(r, "throw"):  # coroutine
            r = await r
    except x_err as err:
        log("Error in %r %r: %r", p, msg, err)
    except Exception as err:  # pylint:disable=broad-exception-caught
        log("Error in %r %r", p, msg, err=err)


def get_part(cur, p: list[str | int]):
    "Walk into a mapping or object structure"
    for pp in p:
        try:
            cur = getattr(cur, pp)
        except (TypeError, AttributeError):
            cur = cur[pp]
    return cur


def set_part(cur, p: list[str | int], v: Any):
    "Modify a mapping or object structure"
    cur = get_part(cur, p[:-1])
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

    @i: seqnum
    @x: excluded errors
    @p: callable
    """

    def __init__(self, cmd: BaseCmd, i: int, x: list[Exception], p: Callable, *a, **k):
        self.cmd = cmd
        self.i = i
        self.p = p
        self.a: list[Any] = a
        self.k: Mapping[str, Any] = k
        self.x = x
        self._t: CancelScope = None

    async def start(self, tg):
        "Task starter. Called from the command."
        if self._t is not None:
            raise RuntimeError("dup")
        self._t = await tg.spawn(self._wrap, _name="Val")

    async def _wrap(self):
        try:
            err = None
            res = await self.p(*self.a, **self.k)
        except Exception as exc:  # pylint:disable=broad-exception-caught
            err = exc
        except BaseException as exc:  # pylint:disable=broad-exception-caught
            err = StoppedError(repr(exc))
        if err is None:
            await self.reply_result(res)
        else:
            await self.cmd.reply_error(self.i, err, self.x)
            if not isinstance(err, Exception):
                raise err

    async def reply_result(self, res):
        "forward the task's return value to the caller"
        await self.cmd.reply_result(self.i, res)

    def cancel(self):
        "cancel the iterator"
        if self._t is not None:
            self._t.cancel()
            self._t = False

    async def set_error(self, err):
        "tell the iterator to raise an error"
        self.cancel()
        await self.cmd.reply_error(self.i, err, self.x)


class IterWrap:
    """
    An iterator that repeatedly calls a function.

    Set @ival to the initial value.
    """

    def __init__(self, p, a=(), k={}, ival=NotGiven):  # pylint:disable=dangerous-default-value
        self.p = p
        self.a = a
        self.k = k
        self.ival = ival

    async def __aenter__(self):
        return self

    async def __aexit__(self, *tb):
        pass

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.ival is NotGiven:
            r = self.p(*self.a, **self.k)
            if hasattr(r, "throw"):  # coroutine
                r = await r
        else:
            r, self.ival = self.ival, NotGiven
        return r


class SendIter(ValueTask):
    """
    The sender of outgoing iterated messages.

    It implements a task that iterates the source and forwards the data.

    When the task ends, a cancellation message is sent to the remote side.

    @cmd: the channel to send to
    @i: seqnum to use
    @r: msec between messages
    @a: action to fetch the iterator from
    @d: data for it
    """

    def __init__(self, cmd, i: int, r: int, a: list[str], d: dict):
        self.r = r
        self.ac = a
        self.ad = d
        super().__init__(cmd, i, (), self._run)

    async def _run(self):
        try:
            cnt = 1
            async with await self.cmd.root.dispatch(self.ac, self.ad, rep=self.r) as it:
                async for msg in it:
                    await self.cmd.s.send({'i': self.i, 'd': msg, 'n': cnt})
                    cnt += 1
        except BaseException:  # pylint:disable=try-except-raise
            raise
        else:
            await self.cmd.s.send({'i': self.i, 'r': False})
        finally:
            self.cmd.reply.pop(self.i, None)

    async def reply_result(self, res):
        "no-op; overrides ValueTask's reply sender."
        pass


class _DelayedIter:
    pass


class DelayedIter(_DelayedIter):
    """
    An iterator that delays calling the wrapped iterator.
    """

    _warned: int = 2
    # warns on the second, fifth, ninth excessive delay
    # don't warn on the first call: starting the iterator
    # might take some extra time

    _i: AsyncIterable = None
    _it: AsyncIterator = None

    def __init__(self, t: int, it: Iterator):
        self.it = it
        self.t = t
        self._next = ticks_add(ticks_ms(), -t)

    async def __aenter__(self):
        self._it = await self.it.__aenter__()
        return self

    async def __aexit__(self, *tb):
        try:
            return await self.it.__aexit__(*tb)
        finally:
            del self._i
            del self._it
            del self.it

    def __aiter__(self):
        self._i = self._it.__aiter__()
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
            if not self._warned & (self._warned - 1):
                # if power of two
                log("IterDelay %r %d", -td)
            self._next = ticks_add(t, self.t)
        return await self._i.__anext__()


class RecvIter(_DelayedIter):
    """
    The recipient of incoming iterated messages.

    It implements an iterator protocol that forwards them to its reader.
    """

    _err = None
    _warned = 1
    cnt = 0

    def __init__(self, cmd, i, t):
        self.cmd = cmd
        self.i = i
        self.t = t
        self._val = ValueEvent()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *err):
        await self.aclose()

    async def aclose(self):
        "close iterator cleanly"
        i, self.i = self.i, None
        if i is not None:
            await self.cmd.s.send({"i": i})

    def __aiter__(self):
        return self

    async def get(self):
        """
        Return the next iterator value.

        May raise `StopAsyncIteration`, or any forwarded non-base exception.
        """
        r = NotGiven
        if self._val is None:
            raise StopAsyncIteration

        try:
            r = await self._val.get()
        except StopAsyncIteration:
            self._val = None
            raise
        else:
            self._val = ValueEvent()
            if self._err is not None:
                self._val.set_error(self._err)
                self._err = None
            return r

        finally:
            if not self._warned:
                # startup is done
                self._warned = 1

    __anext__ = get

    def set_r(self, t):
        """
        Initial value for iterators
        """
        self.t = t
        self._val.set(None)

    def set(self, val, n=0):
        """Set new iterator value.

        This overrides the previous value if it wasn't fetched.
        It may emit a warning in this case.
        """
        if self._val.is_set():
            if self._warned:
                self._warned += 1
            if not self._warned & (self._warned - 1):
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

    def set_error(self, err):
        "tell the iterator to raise an error"
        if self._val.is_set():
            self._err = err
        else:
            self._val.set_error(err)
        self._warned = 0

    def cancel(self):
        "cancel the iterator"
        self._val.set_error(StoppedError("cancel"))
        self._warned = 0
