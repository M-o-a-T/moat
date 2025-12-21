"""
When a channel is lossy, this module implements re-sending messages.
"""

from __future__ import annotations

from contextlib import suppress

from moat.util import NotGiven, Queue, ValueEvent
from moat.lib.codec.errors import ChannelClosed
from moat.util.compat import (
    ACM,
    AC_exit,
    Event,
    TaskGroup,
    TimeoutError,  # noqa:A004
    idle,
    log,
    sleep_ms,
    ticks_add,
    ticks_diff,
    ticks_ms,
    wait_for_ms,
)

from .stack import StackedMsg

from typing import TYPE_CHECKING  # isort:skip

if TYPE_CHECKING:
    from typing import Any


class EphemeralMsg:
    """A message that may be replaced while enqueued or in transit.

    Sending an `EphemeralMsg` enqueues the message without waiting for
    delivery. If a channel's message is waiting to be sent, it'll be
    updated.
    """

    def __init__(self, chan: int, data: Any):
        self.chan = chan
        self.data = data


class ReliableMsg(StackedMsg):
    """
    Message retry.

    This module handles retransmitting missing messages.
    """

    # Operation:
    #
    # Both sender and receiver carry a window-sized array of messages and
    # two position markers: head and tail.
    #
    # Sending, "head" is the next message to be sent, "tail" is the
    # oldest message that's not yet acknowledged. "tail" is populated (if
    # different from "head"), "head" is not, those in between may not be if
    # they have been selectively acknowledged.
    #
    # Receiving, "head" is the next message we expect, "tail" is the oldest
    # message we have not received yet. The data at both "head" and "tail"
    # must be empty (obviously). Between those there may be messages that
    # have been received out of order.
    #
    # Both sender and receiver limit the difference from tail to head to
    # window/2. The sender delays messages that would exceed the window.
    # The receiver discards messages outside of this range.
    #
    # All messages are lists and contain the send_position `s`, recv_tail
    # `r`, recv_done `x`, and data `d`. "recv_done" is a list of messages
    # that have been received out-of-order so they're not retransmitted.
    #
    # 'x' is only present if 'r' is negated (``-1-r``).
    #
    # The receiver advances its send_tail until it matches `r` and queues
    # all messages for retransmission that are still outstanding but not
    # mentioned in `x`. `x` is omitted when empty, `d` is omitted when not
    # yet queued.
    #
    # If data is a list, they're appended as-is to the message, to save a
    # byte, except when the list is one element long, for data
    # transparency.
    #
    # Sending an EphemeralMsg does not wait for delivery. Instead, the
    # message is queued. If the message has not been sent by the time the
    # channel's next message is transmitted, it is updated instead.
    #
    # Connection reset or restart is signalled by `s`<0. Values -2 to -4
    # correspond to restart phases; the following elements contain link
    # configuration data. A value of `-1` indicated that the connection is
    # closed. Other values are reserved.
    #
    # `c` contains of at least two values: the window size and a timeout,
    # in milliseconds. When values do not match, max timeout and min
    # window values are used by both sides. Other items are ignored.
    # A value of zero (or a missing parameter) means "OK I'll take your
    # value" and may only be sent after the corresponding parameter has
    # been seen from the remote.
    #
    # The minimum window size is 4. The minimum timeout is 10 msec, which
    # is probably not useful. The default is 1000 (one second).

    rq = None
    __tg = None

    def __init__(self, link, cfg):
        super().__init__(link, cfg)

        window = cfg.get("window", 8)
        timeout = cfg.get("timeout", 1000)
        retries = cfg.get("retries", 5)

        if window < 4:
            raise RuntimeError(f"window must be >=4, not {window}")
        self.window = window
        self.in_reset = None
        self.timeout = timeout
        self._trigger = Event()
        self._is_up = Event()
        self._is_down = Event()
        self._is_down.set()
        self.retries = retries
        self._iters = {}

    def reset(self, level=1):  # noqa:D102
        self.s_send_head = 0  # next to be transmitted
        self.s_send_tail = 0  # no open messages before this point
        self.s_recv_head = 0  # next expected message. Messages before this are out of sequence
        self.s_recv_tail = 0  # messages before this have been processed
        self.s_q = []
        self.m_send: dict(int, list[Any, int, Event]) = {}  # mte: message timestamp event
        self.m_recv = {}
        self.t_recv = None
        self.progressed = False
        self.in_reset = ticks_ms()
        self.reset_level = level
        self.pend_ack = True
        if self.rq is None:
            self.rq = Queue(self.window)

    async def send_msg(self, k=None):
        """
        Send some message.

        @k: index of whatever to send next, if unacknowledged;
        `None` if only sending an ACK.
        """
        self.progressed = True
        d = NotGiven
        if k is None:
            if not self.pend_ack:
                return
            msg = [self.s_send_head]
        else:
            mte = self.m_send[k]
            if mte[1] is False:
                # already ack'd.
                msg = [self.s_send_head]
            else:
                mte[1] = ticks_add(ticks_ms(), self.timeout)
                msg = [k]
                d = mte[0]
        r = self.s_recv_tail
        x = []
        while r != self.s_recv_head:
            if r in self.m_recv:
                x.append(r)
            r = (r + 1) % self.window
        if x:
            msg.append(-1 - self.s_recv_tail)
            msg.append(x)
        else:
            msg.append(self.s_recv_tail)
        if d is not NotGiven:
            if isinstance(d, EphemeralMsg):
                d.sent = True
                d = d.data
            if isinstance(d, (tuple, list)) and len(d) != 1:
                msg.extend(d)
            else:
                msg.append(d)
        self.pend_ack = False

        with suppress(RuntimeError):
            await self.s.send(msg)

        if k is not None and self.m_send.get(k, None) is mte:
            mte[1] = ticks_add(ticks_ms(), self.timeout)

    async def _run_bg(self):
        while not self.closed:
            if self.in_reset:
                await self._trigger.wait()
                self._trigger = Event()
                continue
            t = ticks_ms()
            # calculate time to next action
            ntx = None if self.t_recv is None else ticks_diff(self.t_recv, t)
            nk = None
            for k, mte in self.m_send.items():
                _m, tx, _e = mte
                if tx is None or tx is False:
                    continue
                txd = ticks_diff(tx, t)
                if ntx is None or ntx > txd:
                    ntx = txd
                    nk = k

            w_open = (
                self.s_q and (self.s_send_head - self.s_send_tail) % self.window < self.window // 2
            )
            if w_open:
                # yes, we can send another message
                # print(f"R {self.link.txt}: tx", file=sys.stderr)
                pass
            elif ntx is None:
                # nothing to do
                # print(f"R {self.link.txt}: inf", file=sys.stderr)
                await self._trigger.wait()
                self._trigger = Event()
            elif ntx > 0:
                # we need to do something soon
                # print(f"R {self.link.txt}: {ntx}", file=sys.stderr)
                try:
                    await wait_for_ms(ntx, self._trigger.wait)
                except TimeoutError:
                    pass
                else:
                    self._trigger = Event()

                # recalculate, as it may have changed during the wait
                w_open = (
                    self.s_q
                    and (self.s_send_head - self.s_send_tail) % self.window < self.window // 2
                )
                # XXX this prevents the "clash" error below but is probably
                # not the real fix
            else:
                # we need to re-send now
                # print(f"R {self.link.txt}: now {ticks_ms()}", file=sys.stderr)
                pass

            # process pending-send queue
            if w_open:
                seq = self.s_send_head
                msg, evt = self.s_q.pop(0)
                nseq = (seq + 1) % self.window
                # print("SH1",self.link.txt,self.s_send_tail,
                #             self.s_send_head,nseq, file=sys.stderr)
                self.s_send_head = nseq
                if seq in self.m_send:
                    raise RuntimeError("Clash")
                self.m_send[seq] = [msg, None, evt]
                await self.send_msg(seq)

            if ntx is not None and ntx <= 0:
                # send a retransmission or a pending ack
                if nk is not None:  # retransmit message K
                    await self.send_msg(nk)
                elif self.pend_ack:
                    await self.send_msg()

                if nk is None:
                    self.t_recv = ticks_add(ticks_ms(), self.timeout)

    async def wait(self):
        """
        Wait until the lower side is (again) ready to be used.

        There is no guarantee that this is still so when you call
        send/recv next.
        """
        while self.closed:
            await self._is_up.wait()

    async def __aenter__(self):
        acm = ACM(self)

        try:
            tg = await acm(TaskGroup())
            if self.retries:
                await tg.spawn(self._mon)
            await tg.spawn(self._run)
            if not self.cfg.get("_nowait"):  # required for testing
                await self.wait()
            self._tg = tg
            return self
        except BaseException as exc:
            await AC_exit(self, type(exc), exc, None)
            raise

    async def __aexit__(self, *err):
        self._tg.cancel()
        self._tg = None
        return await AC_exit(self, *err)

    async def _mon(self):
        while True:
            await wait_for_ms(self.retries * self.timeout, self._is_up.wait)
            await self._is_down.wait()

    async def _run_(self):
        if self._is_down.is_set():
            self._is_down = Event()
        self.reset_level = 1

        try:
            async with TaskGroup() as tg, self.link as s:
                self.__tg = tg
                self.s = s
                await tg.spawn(self._read, _name="rel_read")
                await tg.spawn(self._run_bg, _name="rel_bg")
                while self.in_reset:
                    t = ticks_ms()
                    td = ticks_diff(self.in_reset, t)
                    if td > 0:
                        with suppress(TimeoutError):
                            await wait_for_ms(td, self._trigger.wait)
                        # DO NOT replace self._trigger here. _run_bg() already does that.
                    else:
                        await self.send_reset()

                if self.closed:
                    raise EOFError(self)

                await idle()

        except Exception:  # noqa:TRY203
            # if not self.persist:
            raise
            # log("Reliable", err=exc)

    async def _run(self):
        self.reset()
        try:
            while True:
                await self._run_()
                await sleep_ms(self.timeout)
        except BaseException as exc:
            err = str(exc)
            raise
        else:
            err = None
        finally:
            self.__tg = None
            self._is_down.set()
            for _m, _t, e in self.m_send.values():
                if e is not None:
                    e.set_error(ChannelClosed())
            while self.s_q:
                _m, e = self.s_q.pop()
                if e is not None:
                    e.set_error(ChannelClosed())
            if self._is_up.is_set():
                self._is_up = Event()
            msg = [-1]
            if err is not None:
                msg.append(err)
            try:
                try:
                    await self.s.send(msg)
                except AttributeError:
                    return  # closing. XXX should not happen
                except TypeError:
                    if len(msg) > 1:
                        msg = [msg[0], repr(err)]
                        await self.s.send(msg)
                    else:
                        raise
            except EOFError:
                pass

    async def send_reset(self, level=None, err=None):
        "send a Reset message to the other side"
        if level is None:
            level = self.reset_level
        else:
            self.reset_level = level
        msg = [-1 - level]
        if level:
            msg.extend(self._get_config())
        elif err is not None:
            msg.append(err)
        if self.reset_level < 3:
            self.in_reset = ticks_add(ticks_ms(), self.timeout)
        self._trigger.set()
        await self.s.send(msg)

    async def send(self, msg):
        """
        Sender.

        Ephemeral messages get cached and updated.
        The sender won't wait until they're transmitted.
        """

        if isinstance(msg, EphemeralMsg):
            i = msg.chan
            if (om := self._iters.get(i, None)) is not None:
                om.data = msg.data
                om.sent = False
                return
            self._iters[i] = msg
            msg.sent = False
            evt = None
        else:
            evt = ValueEvent()

        self.s_q.append((msg, evt))
        self._trigger.set()
        if evt is None:
            return
        try:
            return await evt.wait()
        except BaseException:
            # TODO send a cancellation
            # self.s_q.append(({"i": msg["i"]}, None))
            self._trigger.set()
            raise

    def _get_config(self):
        return [self.window, self.timeout]

    def _update_config(self, c):
        if len(c) > 0 and c[0] > 0:
            self.window = max(4, min(self.window, c[0]))
        if len(c) > 1 and c[1] > 0:
            self.timeout = max(10, self.timeout, c[1])

    def _reset_done(self):
        if self.in_reset:
            self.in_reset = False
            self._trigger.set()
            self._is_up.set()

    async def recv(self) -> Any:
        "return the next message in the receive queue"
        return await self.rq.get()

    async def _read(self) -> None:
        while True:
            try:
                if self.s is None:
                    return
                msg = await self.s.recv()
            except EOFError:
                if self.__tg is not None:
                    self.__tg.cancel()
                return
            await self._dispatch(msg)

    @property
    def closed(self) -> bool:
        "check if the link is down"
        return self._is_down.is_set()

    async def _dispatch(self, msg):
        if not isinstance(msg, (tuple, list)):
            raise TypeError(msg)

        if msg[0] < 0:  # protocol error / reset sequence
            n = -1 - msg[0]
            if n == 0:  # closed
                self._is_down.set()
                if self._is_up.is_set():
                    self._is_up = Event()
                self._trigger.set()
            elif self.closed:
                await self.send_reset()
                return
            elif n == 1:  # incoming reset
                if self.in_reset:
                    if self.reset_level == 1:
                        self.reset_level = 2
                else:
                    self.reset(2)

                    await self.error(RuntimeError("ext reset"))
                self._update_config(msg[1:])
                await self.send_reset()
                return
            elif n == 2:  # incoming ack
                self._update_config(msg[1:])
                await self.send_reset(3)
                self._reset_done()
                return
            elif n == 3:  # incoming ack2
                if not self.in_reset or self.reset_level > 1:
                    self._update_config(msg[1:])
                    self._reset_done()
                else:
                    await self.error(RuntimeError("ext reset ack2"))
                    self.reset(1)
                    await self.send_reset()
                return
            else:
                log("Unknown", msg)
                return

        if self.in_reset:
            if self.reset_level < 2:
                await self.send_reset()
                return
            # assume that the other side got our reset=2
            # but their ack got lost
            self._reset_done()

        r = msg[0]  # swapped, because receiving
        s = msg[1]
        if s < 0:
            s = -1 - s
            x = msg[2]
            d = msg[3:]
        else:
            x = ()
            d = msg[2:]

        if not (0 <= r < self.window) or not (0 <= s < self.window):
            self.reset(1)
            await self.send_reset(err="R/S out of bounds")
            return

        if d:
            # data. R is the message's sequence number.
            self.pend_ack = True
            if self.between(self.s_recv_tail, self.s_recv_head, r):
                if (r - self.s_recv_tail) % self.window < self.window // 2:
                    # print("RH1",self.link.txt,self.s_recv_tail,
                    #             self.s_recv_head,r,r+1, file=sys.stderr)
                    self.m_recv[r] = d
                    self.s_recv_head = (r + 1) % self.window
                else:
                    pass
                    # print("RH1-",self.link.txt,self.s_recv_tail,
                    #             self.s_recv_head,r,r+1, file=sys.stderr)
            elif self.between(self.s_recv_tail, r, self.s_recv_head):
                self.m_recv[r] = d

        elif self.between(self.s_recv_tail, self.s_recv_head, r):
            # no data. R is the next-expected sequence number.
            if (r - self.s_recv_tail) % self.window <= self.window // 2:
                self.s_recv_head = r
                # print("RH2",self.link.txt,self.s_recv_tail,
                #             self.s_recv_head,r,r+1, file=sys.stderr)
            else:
                pass
                # print("RH2-",self.link.txt,self.s_recv_tail,
                #             self.s_recv_head,r,r+1, file=sys.stderr)

        # process ACKs
        if True:  # s >= 0:
            rr = self.s_send_tail
            while rr != s:
                if rr == self.s_send_head:
                    # XXX
                    break
                # log("ACKING %d",rr)
                try:
                    m, _t, e = self.m_send.pop(rr)
                except KeyError:
                    pass
                else:
                    if isinstance(m, EphemeralMsg):
                        mo = self._iters.pop(m.chan, None)
                        if not mo.sent:
                            # re-enqueue
                            self.s_q.append((msg, None))

                    self.pend_ack = True
                    if e is not None:
                        e.set(None)
                rr = (rr + 1) % self.window
                self._trigger.set()

            # print("ST1",self.link.txt,self.s_send_tail,self.s_send_head,rr, file=sys.stderr)
            self.s_send_tail = rr

        for rr in x:
            try:
                _m, _t, e = self.m_send[rr]
            except KeyError:
                pass
            else:
                self.m_send[rr][1] = False
                if e is not None:
                    e.set(None)

        # Forward incoming messages if s_recv[recv_tail] has arrived
        rr = self.s_recv_tail
        while rr != self.s_recv_head:
            try:
                d = self.m_recv.pop(rr)
            except KeyError:
                # missing message. Do not proceed.
                break
            else:
                rr = (rr + 1) % self.window
                self.s_recv_tail = rr
                # print("RT1",self.link.txt,self.s_recv_tail,
                #             self.s_recv_head,r,r+1, file=sys.stderr)
                self.pend_ack = True
                if len(d) == 1:
                    d = d[0]
                await self.rq.put(d)

        if self.s_recv_tail == self.s_recv_head:
            self.t_recv = None
        else:
            self.t_recv = ticks_add(ticks_ms(), self.timeout)
            self._trigger.set()

        if self.pend_ack:
            # TODO delay ACK somewhat
            with suppress(EOFError):
                await self.send_msg()

    def between(self, a, b, c):
        "check if a,b,c are consecutive, modulo the window size"
        d1 = (b - a) % self.window
        d2 = (c - a) % self.window
        return d1 <= d2
