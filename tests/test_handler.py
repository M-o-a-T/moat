# test basic message handling

from moatbus.handler import BaseHandler
from moatbus.message import BusMessage

from random import randint,random
from contextlib import asynccontextmanager
from collections import deque
from pprint import pprint

import inspect
import pytest
import time
import os

_seq = 0

max_len=20

def zeroes(len):
    return b'\xFF' * len
def ones(len):
    return b'\xFF' * len
def seq(len):
    return b''.join(bytes((x+1,)) for x in range(len))

class NothingHappensError(RuntimeError):
    pass

class BusTest:
    """
    This is a simulated MoaT bus.
    """
    addr = -2

    def __init__(self, **kw):
        self.clients = set()
        self.off_clients = set()
        for k,v in kw.items():
            setattr(self,k,v)
        self.t = None
        self.time_step = 0
        self.runner = Runner(self)

        self.last = 0
        self.this = None

        self.test_data = 0 # fake
        self.test_timer = 0
        self.reports = deque()

    def get_wire(self):
        return self.last

    def add(self, client):
        self.clients.add(client)

    def remove(self, client):
        self.clients.remove(client)
        if isinstance(client,BaseHandler):
            self.off_clients.add(client)
        if not self.clients:
            self.t = None

    def report(self, n, val, *a):
        t,self.time_step = self.time_step,0
        n = "%3d"%n if n else "---"
        if isinstance(val,int):
            val = "%02x" % val
            assert not a
        elif a:
            val = val % a
        if len(self.reports) > 500:
            self.reports.popleft()
        self.reports.append("%6d %s %s" % (t,n,val))

    def timeout(self):
        if self.this is None:
            return
        if self.last == self.this:
            return
        self.last = self.this
        self.this = None
        self.test_timer = 0

        self.report(0,self.last)
        for c in self.clients:
            c.wire(self.last)

    def wire(self, _):
        pass # dummy

    def check_wires(self):
        val=0
        for c in self.clients:
            val |= c.test_data
        if val == self.last:
            return
        self.this = val
        if self.test_timer <= 0:
            self.test_timer = int(random()*self.max_delay+self.delay)+1

    def run(self):
        self.clients.add(self)
        try:
            while len(self.clients) > 1:
                t = 0
                for c in self.clients:
                    if c.test_timer != 0 and (not t or c.test_timer < t):
                        t = c.test_timer

                if not t:
                    return

                # This is where we don't sleep because we're testing
                if t > 0:
                    self.time_step += t

                #print("T==",t,self.test_timer)
                if self.test_timer:
                    if self.test_timer > t:
                        self.test_timer -= t
                    else:
                        t -= self.test_timer
                        self.test_timer = 0
                        self.timeout()

                for c in list(self.clients):
                    if c is self:
                        continue
                    #print("T=",c.addr,c.test_timer)
                    if c.test_timer:
                        c.test_timer -= t
                        if c.test_timer <= 0:
                            #print("T!",c.addr)
                            c.timeout()

        finally:
            for c in self.clients:
                if isinstance(c, BaseHandler):
                    self.off_clients.add(c)
            del self.clients # drop circular refs
            for c in self.off_clients:
                pprint((c,vars(c)))

    def q(self, proc, *a, **kw):
        self.runner.add(proc,*a,**kw)

class Runner:
    """
    Helper class to feed data to the stream
    """
    addr = -1

    def __init__(self,master):
        self.master = master
        self.queue = deque()
        master.add(self)

        self.test_timer = 0
        self.test_data = 0 # fake

    def add(self, p,*a,**k):
        if not self.queue:
            self.master.add(self)
        self.queue.append((p,a,k))
        if not self.test_timer:
            self.test_timer = 1

    def wire(self, _):
        pass # dummy

    def timeout(self):
        if not self.queue:
            self.master.remove(self)
            return

        r = self.queue.popleft()
        r,a,k = r
        t = r(*a,**k)
        if not self.test_timer:
            self.test_timer = t or 1


class Handler(BaseHandler):
    def __init__(self,master,addr, bits,**kw):
        self.master = master
        self.test_data = 0
        self.errors = []
        self.test_timer = 0
        self.addr = addr
        self.incoming = []

        super().__init__(bits=bits,**kw)

    def debug(self, msg, *a):  
        self.master.report(self.addr, msg, *a)

    def report_error(self, typ, **kw):
        self.errors.append(typ)

    def set_timeout(self, timeout):
        timeout *= self.delay
        f=inspect.currentframe()
        self.master.report(self.addr, "T %d @%d %d %d",timeout,f.f_back.f_lineno,f.f_back.f_back.f_lineno,f.f_back.f_back.f_back.f_lineno)

        self.test_timer = timeout

    def get_wire(self):
        return self.master.get_wire()

    def set_wire(self, bits):
        if self.test_data != bits:
            self.test_data = bits
        f=inspect.currentframe()
        self.master.report(self.addr, "%02x @%d %d %d",bits,f.f_back.f_lineno,f.f_back.f_back.f_lineno,f.f_back.f_back.f_back.f_lineno)

        self.master.check_wires()
        
    def process(self, msg):
        self.incoming.append(msg)
        self.master.report(self.addr, "Rcvd:  %s",msg)
        return msg.dst == self.addr

    def transmitted(self,msg,res):
        self.master.report(self.addr, "Sent:%d %s",res,msg)

def gen_data(client):
    msg = BusMessage()
    msg.src = client.addr
    msg.dst = 3 if client.addr != 3 else 1
    msg.code = 1 if msg.src<4 and msg.dst<4 else 210 if msg.src>4 and msg.dst>4 else 23
    msg.start_send()
    msg.send_data(b'%d!' % client.addr)
    client.send(msg)
    return 30

addrs=[1,3,4,5,8,11,100,131]

@pytest.mark.parametrize('n',[2,4,8])
@pytest.mark.parametrize('bits',[2,3,4])
@pytest.mark.parametrize('delay',[0,4])
@pytest.mark.parametrize('max_delay',[0,4])
@pytest.mark.parametrize('t_a',[11,15])
def test_bus(n,bits, delay,max_delay,t_a):
    bus = BusTest(bits=bits, delay=delay,max_delay=max_delay,t_a=t_a)
    for i in range(n):
        c = Handler(bus,addr=addrs[i],bits=bits, delay=t_a)
        bus.add(c)
        bus.q(gen_data, c)

    bus.run()

    for c in bus.off_clients:
        # Everybody should have received everybody else's messages
        assert len(c.incoming) == n-1, (c.addr,c.incoming)
        for m in c.incoming:
            assert int(m.data[:-1]) == m.src, m
            assert m.data[-1] == b'!'[0], m

