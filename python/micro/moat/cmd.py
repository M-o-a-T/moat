from .compat import Event,ticks_ms,ticks_add,ticks_diff,wait_for_ms,print_exc,spawn,print_exc,CancelledError

from serialpacker import SerialPacker
from msgpack import packb,unpackb
from pprint import pformat

import logging
logger = logging.getLogger(__name__)

#
# Basic infrastructure to run a msgpack-based RPC system
# via an unreliable, possibly-reordering, and/or stream-based
# transport

class RemoteError(RuntimeError):
    pass

class _NotGiven:
    pass

class NotImpl:
    def __init__(self, parent):
        self.parent = parent

    async def dispatch(self,*a):
        raise NotImplementedError(f"{self.parent} {repr(a)}")

    async def open(self):
        pass

    async def close(self):
        pass

    async def error(self, exc):
        pass

class _Stacked:
    def __init__(self, parent, *a,**k):
        self.parent = parent
        self._init(*a,**k)
        self.child = NotImpl(self)

    def _init(self):
        pass

    def stack(self, cls, *a, **k):
        sup = cls(self, *a,**k)
        self.child = sup
        return sup

    async def error(self, exc):
        await self.child.error(exc)

    async def open(self):
        await self.child.open()

    async def close(self):
        await self.child.close()

class Base(_Stacked):
    # Request/response handler (server side)
    # 
    # This is usually attached as a child to the Request object,
    # or stacked. Specific command handlers are attached to this
    # object, by assignment or subclassing or whatever.
    #
    # Incoming requests call `cmd_*` with `*` being the action. If the
    # action is a string, the complete string is tried first, then
    # the first character. Otherwise (action is a list) the first
    # element is used as-is.
    #
    # If the action is empty, call the `cmd` method instead. Otherwise if
    # no method is found fall back to the child.
    # 
    # Attach a sub-base directly to their parents by setting their
    # `cmd_XX` property to it.
    #
    # The `send` method simply forwards to its parent, for convenience.

    async def dispatch(self, action, msg):
        if not action:
            return await self.child.dispatch(msg)

        p = None
        if isinstance(action,str) and action != "":
            try:
                p = getattr(self,"cmd_"+action)
            except AttributeError:
                pass
            else:
                action=""
        if p is None:
            if not action:
                p = self.cmd
            else:
                try:
                    p = getattr(self,"cmd_"+action[0])
                except AttributeError:
                    p = self.child.dispatch
                else:
                    action = action[1:]

        if isinstance(msg,dict):
            return await p(action, **msg)
        else:
            return await p(action, msg)

    __call__ = dispatch

    async def send(self,a,m):
        return await self.parent.send(a,m)

class Request(_Stacked):
    # Request/Response handler (client side)
    # 
    # Call "send" with an action (a string or list) to select
    # the function of the recipient. The response is returned / raised.
    # The second argument is expanded by the recipient if it is a dict
    # 
    # The transport must be reliable.

    def _init(self):
        self.reply = {}
        self.seq = 0

    async def dispatch(self, msg):
        a = msg.pop("a",None)
        i = msg.pop("i",None)
        d = msg.pop("d",None)
        if i is None:
            return await self.child.dispatch(a,m)

        if a is not None: # request
            try:
                res = await self.child.dispatch(a,d)
            except Exception as exc:
                print_exc(exc)
                res = {'e':str(exc),'i':i}
            else:
                res = {'d':res,'i':i}
            await self.parent.send(res)
        else: # reply
            e = msg.pop("e",None) if d is None else None
            try:
                evt = self.reply.pop(i)
            except KeyError:
                return # errored?
            if isinstance(evt,Event):
                self.reply[i] = d if e is None else RemoteError(e)
                evt.set()
            else: # duh. Recorded error? put it back
                self.reply[i] = evt

    async def send(self, action, msg):
        seq = self.seq
        msg = {"a":action,"d":msg,"i":seq}
        self.seq += 1

        e = Event()
        self.reply[seq] = e
        try:
            await self.parent.send(msg)
            await e.wait()
            res = self.reply[seq]
        finally:
            del self.reply[seq]

        if isinstance(res,Exception):
            raise res
        return res

    async def close(self):
        await super().close()
        for k,e in self.reply.items():
            if isinstance(e,Event):
                self.reply[k] = CancelledError()
                e.set()

    async def error(self, err):
        await super().error(err)

        if not isinstance(err,Exception):
            e = RuntimeError(err)

        for k,e in self.reply.items():
            if isinstance(e,Event):
                self.reply[k] = err
                e.set()


class Logger(_Stacked):
    def _init(self, txt):
        self.txt = txt

    async def send(self,a,m=None):
        if m is None:
            m=a
            a=None

        if isinstance(m,dict):
            mm=" ".join(f"{k}={repr(v)}" for k,v in m.items())
        else:
            mm=repr(m)
        if a is None:
            print(f"S:{self.txt} {mm}")
            await self.parent.send(m)
        else:
            print(f"S:{self.txt} {a} {mm}")
            await self.parent.send(a,m)

    async def dispatch(self,a,m=None):
        if m is None:
            m=a
            a=None

        mm=" ".join(f"{k}={repr(v)}" for k,v in m.items())
        if a is None:
            print(f"R:{self.txt} {mm}")
            await self.child.dispatch(m)
        else:
            print(f"R:{self.txt} {a} {mm}")
            await self.child.dispatch(a,m)
        print(f"{self.txt}:\n{pformat(vars(self.child))}")


class Reliable(_Stacked):
    # Message ordering and retry.
    _idle_task = None

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
    # max_open/2. The sender blocks until there is queue space while the
    # receiver discards messages outside this window. However, in practice
    # `max_open/2` SHOULD be sufficiently large to never block the sender.
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
    # 
    # Messages that try to advance a head beyond tail+max_open/2 are
    # discarded. If they persist, the connection is reset.

    def _init(self, max_open=8, timeout=1000):
        if max_open < 4:
            raise RuntimeError(f"max_open must be >=4, not {max_open}")
        self.max_open = max_open
        self.reset_evt = None
        self.in_reset = None
        self.closed = True
        self.timeout = timeout
        self._trigger = Event()

    async def open(self):
        self.closed = False
        self.reset()
        if self._idle_task is None:
            self._idle_task = await spawn(None, self._idle)
        if self.reset_evt is not None:
            await self.reset_evt.wait()
        if not self.closed:
            await self.child.open()
        if self.closed:
            raise RuntimeError("closed")

    async def close(self):
        await super().close()
        self.closed = True
        self._trigger.set()
        if self._idle_task is not None:
            self._idle_task.cancel()

    async def error(self,exc):
        self.closed = True
        print_exc(exc)
        self.reset()
        await self.send_reset(err=str(exc))
        await super().error(exc)

    def reset(self, level=1):
        self.s_send_head = 0 # next to be transmitted
        self.s_send_tail = 0 # no open messages before this point
        self.s_recv_tail = 0 # messages before this have been processed
        self.s_recv_head = 0 # next expected message. Messages before this are out of sequence
        self.s_q = []
        self.m_send = {}
        self.m_recv = {}
        self.t_recv = None
        self.progressed = False
        self.in_reset = ticks_ms()
        self.reset_level = level
        self.pend_ack = True

    async def send_msg(self, k=None,m=None):
        self.progressed = True
        if k is not None:
            self.m_send[k] = (m,ticks_add(ticks_ms(),self.timeout))
            msg = {'s':k, 'd':m}
        else:
            if not self.pend_ack:
                return
            msg = {'s':self.s_send_head}
        msg['r'] = r = self.s_recv_tail
        x = []
        while r != self.s_recv_head:
            if r in self.m_recv:
                x.append(r)
            r = (r+1) % self.max_open
        if x:
            msg['x'] = x
        self.pend_ack = False

        try:
            await self.parent.send(msg)
        except RuntimeError:
            print("NOSEND RESET",self.reset_level)
            pass

        if k is not None and k in self.m_send:
            self.m_send[k] = (m,ticks_add(ticks_ms(),self.timeout))


    async def _idle_work(self, t):
        # check for possible retransmit requirement
        sent = False

        # calculate time to next action
        ntx = None if self.t_recv is None else ticks_diff(self.t_recv,t)
        nm = None
        nk = None
        for k,mtx in self.m_send.items():
            m,tx = mtx
            txd = ticks_diff(tx,t)
            if ntx is None or ntx > txd:
                ntx = txd
                nm = m
                nk = k

        if self.s_q and (self.s_send_head - self.s_send_tail) % self.max_open < self.max_open//2:
            pass
            #print(f"R {self.parent.txt}: tx")
        elif ntx is None:
            #print(f"R {self.parent.txt}: inf")
            await self._trigger.wait()
            self._trigger = Event()
        elif ntx > 0:
            if ntx > self.timeout*10:
                import pdb;pdb.set_trace()
            #print(f"R {self.parent.txt}: {ntx}")
            try:
                await wait_for_ms(ntx,self._trigger.wait)
            except TimeoutError:
                pass
            else:
                self._trigger = Event()
        else:
            pass
            #print(f"R {self.parent.txt}: now {ticks_ms()}")
        if self.in_reset:
            return

        # process pending-send queue
        if self.s_q and (self.s_send_head - self.s_send_tail) % self.max_open < self.max_open//2:
            seq = self.s_send_head
            msg = self.s_q.pop(0)
            nseq = (seq+1)%self.max_open
            #print("SH1",self.parent.txt,self.s_send_tail,self.s_send_head,nseq)
            self.s_send_head = nseq
            await self.send_msg(seq,msg)
            sent = True

        if ntx is not None and ntx <= 0: # work
            if nm is not None: # retransmit message K
                await self.send_msg(nk,nm)
                sent = True
            if self.pend_ack:
                await self.send_msg()

            if nm is None:
                self.t_recv = ticks_add(ticks_ms(),self.timeout)


    async def _idle(self):
        try:
            while not self.closed:
                try:
                    t = ticks_ms()
                    if self.in_reset:
                        td = ticks_diff(self.in_reset,t)
                        #print(f"R {self.parent.txt}: reset {td} {t} {self.in_reset}")
                        if td > 0:
                            try:
                                await wait_for_ms(td,self._trigger.wait)
                            except TimeoutError:
                                pass
                            else:
                                self._trigger = Event()
                        else:
                            await self.send_reset()
                    else:
                        await self._idle_work(t)

                except Exception as exc:
                    await self.error(exc)
        finally:
            self._idle_task = None

    async def send_reset(self, level=0, err=None):
        if level:
            self.reset_level = level
        msg = {'a':'r', 'n':self.reset_level}
        if err is not None:
            msg['e'] = err
            await self.child.error(err)
        if self.reset_level < 3:
            if self.reset_evt is None or self.reset_evt.is_set():
                self.reset_evt = Event()
            self.in_reset = ticks_add(ticks_ms(),self.timeout)
        self._trigger.set()
        try:
            await self.parent.send(msg)
        except RuntimeError:
            print("NOSEND RESET",self.reset_level)
            pass

    async def _wait_reset(self):
        e = self.reset_evt
        if e is None:
            return
        await e.wait()
        if self.reset_evt is e:
            self.reset_evt = None

    async def send(self, msg):
        self.s_q.append(msg)
        self._trigger.set()

    def _get_config(self):
        return {'t':self.timeout,'m':self.max_open}

    def _update_config(self, c):
        self.timeout = max(self.timeout,c.get('t',0))
        self.max_open = max(4,min(self.max_open,c.get('m',self.max_open)))

    def _reset_done(self):
        if self.in_reset:
            self.in_reset = False
            self._trigger.set()
            self.reset_evt.set()

    async def dispatch(self, msg):
        a = msg.get('a',None)

        if a is None:
            pass
        elif a == 'r':
            c = msg.get('c',{})
            n = msg.get('n',0)
            e = msg.get('e',None)
            if n == 1: # incoming reset
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
                await self.send_reset(3)
                self._reset_done()
                return
            elif n == 3: # incoming ack2
                if not self.in_reset or self.reset_level > 1:
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
            return ## unknown

        if self.in_reset:
            if self.reset_lejjvel < 2:
                await self.send_reset()
                return
            self._reset_done()

        r = msg.get('s',None) # swapped (our PoV of incoming msg)
        s = msg.get('r',None)
        x = msg.get('x',())

        if r is None or s is None:
            return
        if not (0<=r<self.max_open) or not (0<=s<self.max_open):
            self.reset(1)
            await self.send_reset(err="R/S out of bounds")
            return

        d = msg.get('d', _NotGiven)
        if d is not _NotGiven:
            # data. R is the message's sequence number.
            self.pend_ack = True
            if self.between(self.s_recv_tail,self.s_recv_head,r):
                if (r-self.s_recv_tail)%self.max_open < self.max_open//2:
                    #print("RH1",self.parent.txt,self.s_recv_tail,self.s_recv_head,r,r+1)
                    self.m_recv[r] = d
                    self.s_recv_head = (r+1) % self.max_open
                else:
                    pass
                    #print("RH1-",self.parent.txt,self.s_recv_tail,self.s_recv_head,r,r+1)
            elif self.between(self.s_recv_tail,r,self.s_recv_head):
                self.m_recv[r] = d

        elif self.between(self.s_recv_tail,self.s_recv_head,r):
            # no data. R is the next-expected sequence number.
            if (r-self.s_recv_tail)%self.max_open <= self.max_open//2:
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
                    del self.m_send[rr]
                except KeyError:
                    pass
                else:
                    self.pend_ack = True
                rr = (rr+1) % self.max_open
                self._trigger.set()

            #print("ST1",self.parent.txt,self.s_send_tail,self.s_send_head,rr)
            self.s_send_tail = rr

        for rr in x:
            try:
                del self.m_send[rr]
            except KeyError:
                pass

        # Forward incoming messages if s_recv[recv_tail] has arrived
        rr = self.s_recv_tail
        while rr != self.s_recv_head:
            try:
                d = self.m_recv.pop(rr)
            except KeyError:
                break
            else:
                rr = (rr+1) % self.max_open
                self.s_recv_tail = rr
                #print("RT1",self.parent.txt,self.s_recv_tail,self.s_recv_head,r,r+1)
                self.pend_ack = True
                await self.child.dispatch(d)

        if self.s_recv_tail == self.s_recv_head:
            self.t_recv = None
        else:
            self.t_recv = ticks_add(ticks_ms(),self.timeout)
            self._trigger.set()

        if self.pend_ack:
            # TODO delay ACK somewhat
            await self.send_msg()

    def between(self, a,b,c):
        d1 = (b-a)%self.max_open
        d2 = (c-a)%self.max_open
        return d1 <= d2

class SerialPackHandler(_Stacked):
    # interfaces a message stream packetized by SerialPacker
    # may require a reliable on top if the serial line is lossy
    # it is probably lossless when using USB
    #
    def __init__(self, stream, evt=None, **kw):
        super().__init__(None)

        self.s = stream
        self.p = SerialPacker(**kw)
        self.evt = evt
        self.buf = bytearray()

    async def stream_in(self, b):
        # console data stream, i.e. anything not packetized
        if b[0] in (3,4):
            if self.evt is not None:
                self.evt.set()
        elif b[0] != 0x0A:
            self.buf.extend(b)
        elif self.buf:
            try:
                print(eval(self.buf.decode("utf-8")))
            except Exception as exc:
                print_exc(exc)
            self.buf = bytearray()

    async def run(self, evt):
        while True:
            c = await self.s.read(1)
            if not c:
                raise EOFError
            msg = self.p.feed(c[0])
            if msg is None:
                # primitive console
                b = self.p.read()
                if not b:
                    continue
                await self.stream_in(b)

            else:
                try:
                    res = None
                    msg = unpackb(msg)
                    await spawn(evt, self.child.dispatch, msg)
                except Exception as exc:
                    print(f"Processing {msg} to {res}")
                    print_exc(exc)

    async def send(self, msg):
        msg = packb(msg)
        h,t = self.p.frame(msg)
        await self.s.write(h+msg+t)

    async def close(self):
        await self.child.close()
