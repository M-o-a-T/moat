from .compat import Event,sleep,ticks_ms,ticks_add,ticks_diff,wait_for_ms,print_exc,spawn,print_exc

from serialpacker import SerialPacker
from msgpack import packb,unpackb

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
            try:
                return await self.child.dispatch(msg)
            except Exception:
                import pdb;pdb.set_trace()
                raise

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

        if a is not None:
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
            evt = self.reply.pop(i)
            self.reply[i] = d if e is None else RemoteError(e)
            evt.set()

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
        self.ack_evt = None
        self.reset()
        self.in_reset = None
        self.closing = False
        self.timeout = timeout
        self._trigger = Event()
        self._idle_task = None

    def reset(self, did_recv=False):
        self.s_send_head = 0 # next to be transmitted
        self.s_send_tail = 0 # no open messages before this point
        self.s_recv_tail = 0 # messages before this have been processed
        self.s_recv_head = 0 # next expected message. Messages before this are out of sequence
        self.m_send = {}
        self.m_recv = {}
        self.t_recv = None
        self.blocked_send = []
        self.in_reset = ticks_ms()
        if self._idle_task is None:
            self._idle_task = spawn(None, self._idle)

    async def send_msg(self, k=None,m=None):
        if k is not None:
            self.m_send[k] = (m,ticks_add(ticks_ms(),self.timeout))
            msg = {'s':k, 'd':m}
        else:
            msg = {'s':self.s_send_head}
        msg['r'] = r = self.s_recv_tail
        x = []
        while r != self.s_recv_head:
            if r in self.self.m_recv:
                x.append(r)
            r = (r+1) % self.max_open
        if x:
            msg['x'] = x
        # TODO set 
        await self.send(msg)

        if k is not None and k in self.m_send:
            self.m_send[k] = (m,ticks_add(ticks_ms(),self.timeout))

    async def _idle_work(self, t):
        # check for possible retransmit requirement

        # calculate time to next action
        ntx = self.t_recv
        nm = None
        nk = None
        for k,mtx in self.m_send.values():
            m,tx = mtx
            txd = ticks_sub(tx,t)
            if ntx is None or ntx > txd:
                ntx = txd
                nm = m
                nk = k

        if ntx is None:
            await self._trigger.wait()
        elif ntx > 0:
            try:
                await wait_for_ms(ntx,self._trigger.wait)
            except TimeoutError:
                pass

        if self._trigger.is_set():
            self._trigger = Event()

        if ntx <= 0: # work
            if nm is None: # just send an ack
                await self.send_msg()
            else: # retransmit message K
                self.m_send[k] = (m,ticks_add(ticks_ms(),self.timeout))
                await self.send_msg(k,m)
                if k in self.m_send:
                    # might have been acked during send
                    self.m_send[k] = (m,ticks_add(ticks_ms(),self.timeout))


    async def _idle(self):
        try:
            while not self.closing:
                t = ticks_ms()
                if self.in_reset is None:
                    await self._idle_work(t)
                else:
                    td = ticks_diff(t,self.in_reset)
                    if td > 0:
                        await sleep(td)
                    else:
                        await self.send_reset()

        except Exception as exc:
            await self.error(exc)
        finally:
            self._idle_task = None


    async def close(self):
        self.closing = True
        self._trigger.set()
        if self._idle_task is not None:
            self._idle_task.cancel()
        await super().close()

    async def send_reset(self):
        msg = {'s':-1,'r':-1,'c':{'t':self.timeout,'m':self.max_open}}
        if self.ack_evt is None:
            self.ack_evt = Event()
        self.in_reset = ticks_add(ticks_ms(),self.timeout)
        self._trigger.set()
        await self.parent.send(msg)

    async def _wait(self):
        if (e := self.ack_evt) is None:
            self.ack_evt = e = Event()
        await e.wait()
        if self.ack_evt is e:
            self.ack_evt = None

    async def send(self, msg):
        if self.in_reset is None:
            await self.send_reset()

        while self.in_reset:
            await self._wait()

        seq = self.s_send_head
        nseq = (seq+1)%self.max_open
        if nseq == self.s_send_tail:
            # Too many open requests. Queue me.
            evt = Event()
            self.blocked_send.append(evt)
            await evt.wait()

            seq = self.s_send_head
            nseq = (seq+1)%self.max_open
            if nseq == self.s_send_tail:
                raise RuntimeError("major owch")
        self.s_send_head = nseq

        await self.send_msg(seq,msg)
        self._trigger.set()

        await self.parent.send(msg)

    async def dispatch(self, msg):
        r = msg.get('s',-1)
        s = msg.get('r',-1)
        x = msg.get('x',())

        if s < 0 and r < 0: # reset
            c = msg.get('c',{})
            self.timeout = max(self.timeout,c.get('t',0))
            self.max_open = max(4,min(self.max_open,c.get('m',self.max_open)))
            self.reset(None)
            if self.in_reset is None:
                await self.send_reset()
            await self.parent.send({'s':0,'r':0,'c':{'t':self.timeout,'m':self.max_open}})
            return
        elif self.in_reset is not None and s == 0 and r == 0:
            c = msg.get('c',{})
            self.timeout = max(self.timeout,c.get('t',0))
            self.max_open = max(4,min(self.max_open,c.get('m',self.max_open)))

            self.in_reset = None
            self.ack_evt.set()
            return
        print(f"run {r} {s}")

        d = msg.get('d', _NotGiven)
        if d is not _NotGiven:
            self.m_recv[r] = d
            self.t_recv = ticks_add(ticks_ms(),self.timeout)
        do_ack = None # tristate

        if r >= 0 and self.between(self.s_recv_tail,self.s_recv_head,r):
            r = (r+1) % self.max_open
            self.s_recv_head = r

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
                    do_ack = False
                rr = (rr+1) % self.max_open
                if self.blocked_send:
                    self.blocked_send.pop(0).set()
            self.s_send_tail = rr

        for rr in x:
            try:
                del self.m_send[rr]
            except KeyError:
                pass

        # process incoming messages
        rr = self.s_recv_tail
        while rr != self.s_recv_head:
            try:
                d = self.m_recv.pop(rr)
            except KeyError:
                break
            else:
                do_ack = True
                rr = (rr+1) % self.max_open
                await self.child.dispatch(d)
        self.s_recv_tail = rr

        if self.s_revc_head== self.s_recv_head:
            self.t_recv = None
        else:
            self._trigger.set()

        if do_ack:
            await self.send_msg()

        if do_ack is not None and self.ack_evt is not None:
            self.ack_evt.set()

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

    async def run(self):
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
                    res = spawn(self.dispatch, msg)
                    if res is not None:
                        res = packb(res)
                        await self.send(res)
                except Exception as exc:
                    print(f"Processing {msg} to {res}")
                    print_exc(exc)

    async def send(self, msg):
        msg = packb(msg)
        h,t = self.p.frame(msg)
        await self.s.write(h+msg+t)

    async def close(self):
        await self.child.close()
