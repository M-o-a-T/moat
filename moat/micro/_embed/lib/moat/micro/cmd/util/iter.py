"""
Helpers for MoaT command interpreters et al.
"""

from __future__ import annotations

from moat.util import NotGiven, ValueEvent
from moat.micro.compat import (
    L,
    log,
    sleep_ms,
    ticks_add,
    ticks_diff,
    ticks_ms,
)
from moat.micro.errors import StoppedError

from .valtask import ValueTask

# Typing

from typing import TYPE_CHECKING  # isort:skip

if TYPE_CHECKING:
    from collections.abc import AsyncIterable, AsyncIterator, Iterator


if not L:
    raise RuntimeError("not Large")


class IterWrap:
    """
    An iterator that repeatedly calls a function.

    Set @ival to the initial value.
    """

    def __init__(self, p, a=(), k={}, ival=NotGiven):  # noqa:B006 pylint:disable=dangerous-default-value
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

    _IT = True

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
                    await self.cmd.s.send({"i": self.i, "d": msg, "n": cnt})
                    cnt += 1

            await self.cmd.s.send({"i": self.i, "r": False})
        finally:
            self.cmd.reply.pop(self.i, None)

    async def reply_result(self, res):
        "no-op; overrides ValueTask's reply sender."


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
        elif self.t > 10:  # XXX add explicit param whether to warn?
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

    _IT = True

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
                log(f"Missed {n - self.cnt}")
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
