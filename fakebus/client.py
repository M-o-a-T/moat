
import anyio
import trio
from moatbus.handler import BaseHandler, ERR
from contextlib import asynccontextmanager
import time
import sys

class Client(BaseHandler):
    def __init__(self, wires, timeout=0.01, timeout2=0.005, socket="/tmp/moatbus", verbose=False, dest=None):
        self.__socket = socket
        self.__timeout = timeout
        self.__timeout2 = timeout2
        self.__dest = dest

        self.__msg = None
        self.__wire_in = 0
        self.__wire_out = None
        self.__evt = {}
        self.__done = []
        self.__c = None
        self.__t = None
        self.__v = verbose

        super().__init__(wires=wires)

    async def main(self, task_status):
        task_status.started()
        while True:
            if self.__t is not None:
                t1 = time.monotonic()
            if self.__msg is not None:
                m,self.__msg = self.__msg,None
                await self.__q.put(m)
            if self.__wire_out is not None:
                b,self.__wire_out = self.__wire_out,None
                await self.__sock.send_all(bytes((b,)))
            if self.__done:
                d,self.__done = self.__done,[]
                for ev in d:
                    await ev.set()

            try:
                b = None
                if self.__t is None:
                    with trio.CancelScope() as c:
                        self.__kick = c
                        b = await self.__sock.receive_some(1)
                else:
                    with trio.fail_after(max(self.__t/1000,0)) as c:
                        self.__kick = c
                        b = await self.__sock.receive_some(1)
            except anyio.exceptions.ClosedResourceError:
                return
            except (trio.TooSlowError,TimeoutError):
                self.__c = None
                self.__t = None
                self.timeout()
            else:
                self.__c = None
                if b is None:
                    pass
                elif not b:
                    sys.exit(1)
                if self.__t is not None:
                    t2 = time.monotonic()
                    t1,t2 = t2,t2-t1
                    self.__t -= t2

                if b:
                    self.__wire_in = b[0]
                    self.debug("WIRE %r",b)
                    self.wire(b[0])
                if self.__t is not None and self.__t <= 0:
                    self.__t = None
                    self.timeout()

    async def send(self, prio, msg):
        mi = id(msg)
        if mi in self.__evt:
            raise RuntimeError("Already sending")
        self.__evt[mi] = ev = anyio.create_event()
        super().send(msg,prio)
        await ev.wait()
        return self.__evt.pop(mi)

    def get_wire(self):
        return self.__wire_in

    def set_wire(self, wire):
        self.__wire_out = wire
        if self.__c is not None:
            self.__c.cancel()

    def transmitted(self, msg, res):
        msg.res=res
        self.debug("SENT %r %s",msg,res)
        mi = id(msg)
        ev = self.__evt.pop(mi)
        self.__evt[mi] = res
        self.__done.append(ev)

    def process(self, msg):
        if self.__dest is not None and self.__dest == msg.dst:
            self.__msg = msg
            return True
        elif self.__dest is None:
            self.__msg = msg

    def report_error(self, typ, **kw):
        if kw:
            self.debug("ERROR %s %s",typ,kw)
        else:
            self.debug("ERROR %s",typ)
        if typ == ERR.COLLISION:
            print("COLL",kw)
        #import pdb;pdb.set_trace()
        pass # ERROR

    def debug(self, msg, *a):
        if not self.__v:
            return
        if a:
            msg %= a
        print(msg)
        pass

    def set_timeout(self, t):
        self.debug("TIME %f",t)
        if self.__c is not None:
            self.__c.cancel()
        if t < 0:
            self.__t = None
        elif t:
            self.__t = self.__timeout*t
        else:
            self.__t = self.__timeout2

    @asynccontextmanager
    async def run(self):
        async with trio.open_nursery() as tg, \
                await anyio.connect_unix(self.__socket) as sock:
            self.__tg = tg
            self.__sock = sock
            self.__q = anyio.create_queue(100)

            await tg.start(self.main)
            try:
                yield self
            except anyio.exceptions.ClosedResourceError:
                pass

    def __aiter__(self):
        return self

    def __anext__(self):
        return self.__q.get()
