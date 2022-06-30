from ..compat import Event,ticks_ms,ticks_add,ticks_diff,wait_for_ms,TaskGroup

import logging
logger = logging.getLogger(__name__)

from . import _Stacked

class Reliable(_Stacked):
    # Message ordering and retry.

    # Both sender and receiver carry two message counter: head and tail.
    #
    # Sending, "head" is the next message to be sent, "tail" points to the
    # oldest message that's not yet acknowledged. "tail" is populated (if
    # different from "head"), "head" is not, those in between may not be if
    # they have been selectively acknowledged.
    #
    # Receiving, "head" is the next message we expect, "tail" is the first
    # message we have not received yet. The data at both "head" and "tail"
    # must be empty (obviously). Between those there may be messages that
    # have been received out of order.
    # 
    # Both sender and receiver limit the difference from tail to head to
    # window/2. The sender blocks until there is queue space while the
    # receiver discards messages outside this window. In order not to block
    # its clients, the sender also maintains a queue of waiting packets.
    #
    # All messages contain send_head `s`, recv_tail `r`, recv_done `x`,
    # and data `d`. "recv_done" is the list of messages that have been
    # received out-of-order so they're not retransmitted.
    # The receiver advances its send_tail until it matches `r` and queues
    # all messages for retransmission that are still outstanding but not
    # mentioned in `x`.
    # 
    # Connection reset is signalled by s=r=-1 and answered with s=r=0
    # before regular message exchange can take place. This exchange must
    # happen in both directions. Other messages received during a reset
    # are discarded.

    async def __init__(self, parent, window=8, timeout=1000, **k):
        await super().__init__(parent, **k)

        if window < 4:
            raise RuntimeError(f"window must be >=4, not {window}")
        self.window = window
        self.reset_evt = None
        self.in_reset = None
        self.timeout = timeout
        self._trigger = Event()
        self.closed = True

    def reset(self, level=1):
        self.s_send_head = 0 # next to be transmitted
        self.s_send_tail = 0 # no open messages before this point
        self.s_recv_head = 0 # next expected message. Messages before this are out of sequence
        self.s_recv_tail = 0 # messages before this have been processed
        self.s_q = []
        self.m_send = {}
        self.m_recv = {}
        self.t_recv = None
        self.progressed = False
        self.in_reset = ticks_ms()
        self.reset_level = level
        self.pend_ack = True
        self.closed = False

    async def send_msg(self, k=None):
        self.progressed = True
        if k is None:
            if not self.pend_ack:
                return
            msg = {'s':self.s_send_head}
        else:
            mte = self.m_send[k]
            mte[1] = ticks_add(ticks_ms(),self.timeout)
            msg = {'s':k, 'd':mte[0]}
        msg['r'] = r = self.s_recv_tail
        x = []
        while r != self.s_recv_head:
            if r in self.m_recv:
                x.append(r)
            r = (r+1) % self.window
        if x:
            msg['x'] = x
        self.pend_ack = False

        try:
            await self.parent.send(msg)
        except RuntimeError:
            print("NOSEND RESET",self.reset_level)
            pass

        if k is not None and self.m_send.get(k,None) is mte:
             mte[1] = ticks_add(ticks_ms(),self.timeout)


    async def _run(self, tg):
        self.tg = tg
        await tg.spawn(self._read)

        while not self._closed:
            t = ticks_ms()
            # calculate time to next action
            ntx = None if self.t_recv is None else ticks_diff(self.t_recv,t)
            nk = None
            for k,mte in self.m_send.items():
                m,tx,e = mtx
                txd = ticks_diff(tx,t)
                if ntx is None or ntx > txd:
                    ntx = txd
                    nk = k

            if self.s_q and (self.s_send_head - self.s_send_tail) % self.window < self.window//2:
                pass
                #print(f"R {self.parent.txt}: tx")
            elif ntx is None:
                #print(f"R {self.parent.txt}: inf")
                await self._trigger.wait()
                self._trigger = Event()
            elif ntx > 0:
                #print(f"R {self.parent.txt}: {ntx}")
                try:
                    await wait_for_ms(ntx, self._trigger.wait)
                except TimeoutError:
                    pass
                else:
                    self._trigger = Event()
            else:
                pass
                #print(f"R {self.parent.txt}: now {ticks_ms()}")
            if self.in_reset or self.closed:
                return

            # process pending-send queue
            if self.s_q and (self.s_send_head - self.s_send_tail) % self.window < self.window//2:
                seq = self.s_send_head
                msg,evt = self.s_q.pop(0)
                nseq = (seq+1)%self.window
                #print("SH1",self.parent.txt,self.s_send_tail,self.s_send_head,nseq)
                self.s_send_head = nseq
                self.m_send[seq] = [msg,None,evt]
                await self.send_msg(seq)

            if ntx is not None and ntx <= 0: # work
                if nk is not None: # retransmit message K
                    await self.send_msg(nk)
                if self.pend_ack:
                    await self.send_msg()

                if nk is None:
                    self.t_recv = ticks_add(ticks_ms(),self.timeout)

    async def run(self):
        self.reset()
        try:
            while self.in_reset:
                t = ticks_ms()
                td = ticks_diff(self.in_reset,t)
                #print(f"R {self.parent.txt}: reset {td} {t} {self.in_reset}")
                if td > 0:
                    try:
                        await wait_for_ms(td, self._trigger.wait)
                    except TimeoutError:
                        pass
                    else:
                        self._trigger = Event()
                else:
                    await self.send_reset()

            async with TaskGroup() as tg:
                runner = await tg.spawn(self._run, tg)
                await self.client.run()
                runner.cancel()
                self.tg = None

        except Exception as exc:
            err = str(exc)
            raise
        else:
            err = None
        finally:
            self._closed = True
            for _m,_t,e in self.m_send.values():
                e.set()
            for _m,e in self.s_q.pop():
                e.set()
            msg = {'a':'r', 'n':0}
            if err is not None:
                msg['err'] = err
            await self.send(msg)

    async def send_reset(self, level=0, err=None):
        if self.closed:
            level = 0
        elif level:
            self.reset_level = level
        else:
            level = self.reset_level
        msg = {'a':'r', 'n':level}
        if level:
            msg['c'] = self._get_config()
        if err is not None:
            msg['e'] = err
        if self.reset_level < 3:
            if self.reset_evt is None or self.reset_evt.is_set():
                self.reset_evt = Event()
            self.in_reset = ticks_add(ticks_ms(),self.timeout)
        self._trigger.set()
        await self.parent.send(msg)

    async def send(self, msg):
        evt = Event()
        self.s_q.append((msg,evt))
        self._trigger.set()
        await evt.wait()
        if self.closed:
            raise ChannelClosed()
            # always an error.

    def _get_config(self):
        return {'t':self.timeout,'m':self.window}

    def _update_config(self, c):
        self.timeout = max(self.timeout,c.get('t',0))
        self.window = max(4,min(self.window,c.get('m',self.window)))

    def _reset_done(self):
        if self.in_reset:
            self.in_reset = False
            self._trigger.set()
            self.reset_evt.set()

    async def _read(self):
        while True:
            msg = await self.parent.recv()
            await self.dispatch(msg)

    async def dispatch(self, msg):
        a = msg.get('a',None)

        if a is None:
            pass
        elif a == 'r':
            c = msg.get('c',{})
            n = msg.get('n',0)
            e = msg.get('e',None)
            if n == 0: # closed
                self.closed = True
                self._trigger.set()
            elif self.closed:
                await self.send_reset()
                return
            elif n == 1: # incoming reset
                if self.in_reset:
                    if self.reset_level == 1:
                        self.reset_level = 2
                else:
                    self.reset(2)
                    await self.error(RuntimeError(e or "ext reset"))
                self._update_config(c)
                await self.send_reset()
                return
            elif n == 2: # incoming ack
                self._update_config(c)
                await self.send_reset(3)
                self._reset_done()
                return
            elif n == 3: # incoming ack2
                if not self.in_reset or self.reset_level > 1:
                    self._update_config(c)
                    self._reset_done()
                else:
                    await self.error(RuntimeError("ext reset ack2"))
                    self.reset(1)
                    await self.send_reset()
                return
            else:
                # ignored
                return
        else:
            return ## unknown action

        if self.closed:
            # if we're down, reply with a reset, but not every time
            if self.reset_level > 2:
                await self.send_reset()
                self.reset_level = 0
            else:
                self.reset_level += 1
            return

        if self.in_reset:
            if self.reset_level < 2:
                await self.send_reset()
                return
            self._reset_done()

        r = msg.get('s',None) # swapped (our PoV of incoming msg)
        s = msg.get('r',None)
        x = msg.get('x',())

        if r is None or s is None:
            return
        if not (0<=r<self.window) or not (0<=s<self.window):
            self.reset(1)
            await self.send_reset(err="R/S out of bounds")
            return

        d = msg.get('d', _NotGiven)
        if d is not _NotGiven:
            # data. R is the message's sequence number.
            self.pend_ack = True
            if self.between(self.s_recv_tail,self.s_recv_head,r):
                if (r-self.s_recv_tail)%self.window < self.window//2:
                    #print("RH1",self.parent.txt,self.s_recv_tail,self.s_recv_head,r,r+1)
                    self.m_recv[r] = d
                    self.s_recv_head = (r+1) % self.window
                else:
                    pass
                    #print("RH1-",self.parent.txt,self.s_recv_tail,self.s_recv_head,r,r+1)
            elif self.between(self.s_recv_tail,r,self.s_recv_head):
                self.m_recv[r] = d

        elif self.between(self.s_recv_tail,self.s_recv_head,r):
            # no data. R is the next-expected sequence number.
            if (r-self.s_recv_tail)%self.window <= self.window//2:
                self.s_recv_head = r
                #print("RH2",self.parent.txt,self.s_recv_tail,self.s_recv_head,r,r+1)
            else:
                pass
                #print("RH2-",self.parent.txt,self.s_recv_tail,self.s_recv_head,r,r+1)

        # process ACKs
        if s >= 0:
            rr = self.s_send_tail
            while rr != s:
                if rr == self.s_send_head:
                    # XXX
                    break
                try:
                    _m,_t,e = self.m_send.pop(rr)
                except KeyError:
                    pass
                else:
                    self.pend_ack = True
                    e.set()
                rr = (rr+1) % self.window
                self._trigger.set()

            #print("ST1",self.parent.txt,self.s_send_tail,self.s_send_head,rr)
            self.s_send_tail = rr

        for rr in x:
            try:
                _m,_t,e = self.m_send[rr]
            except KeyError:
                pass
            else:
                e.set()

        # Forward incoming messages if s_recv[recv_tail] has arrived
        rr = self.s_recv_tail
        while rr != self.s_recv_head:
            try:
                d = self.m_recv.pop(rr)
            except KeyError:
                break
            else:
                rr = (rr+1) % self.window
                self.s_recv_tail = rr
                #print("RT1",self.parent.txt,self.s_recv_tail,self.s_recv_head,r,r+1)
                self.pend_ack = True
                await self.tg.spawn(self.child.dispatch, d)

        if self.s_recv_tail == self.s_recv_head:
            self.t_recv = None
        else:
            self.t_recv = ticks_add(ticks_ms(),self.timeout)
            self._trigger.set()

        if self.pend_ack:
            # TODO delay ACK somewhat
            await self.send_msg()

    def between(self, a,b,c):
        d1 = (b-a)%self.window
        d2 = (c-a)%self.window
        return d1 <= d2
