"""
Gateway to wherever: node data
"""

from __future__ import annotations
from attrs import define,field
import anyio
from moat.link.node import Node
from moat.util import Path, NotGiven, P, t_iter

UPDATE_TIMEOUT=15

@define
class BaseGateway:
    src:Node
    dst:Node



    async def update(src:Path, data:Any):




    def updated(self):
        try:
            self.dest = Path.build(self.data.dest)

    
    def send(self, k):
        s=super()._add(k)
        s.path=self.path/k
        s.gate=self.gate
        s.tg=self.tg
        self.tg.start_soon(self.run)
        return s

    def set(self,*a,**kw):
        res = super().set(*a,**kw)
        if res:
            self.node_updated.set()

    async def work(self, *, task_status):
        task_status.started()
        c=self.gate.client
        p=P(":r.run")+self.gate.path+self.path
        n=0
        while True:
            n += 1
            await c.send(p,n)
            try:
                async with c.e_wrap(self.path):
                    await getattr(self,f"work_{d.dir}")()
            except anyio.get_cancelled_exc_class():
                with anyio.move_on_after(2,shield=True):
                    await c.send(p,False)
                raise
            except Exception:
                self.backoff = min(60,self.backoff*1.3+.1)
                await c.send(p,("Exc",repr(exc)),self.backoff)
                await anyio.sleep(self.backoff)
            except BaseException as exc:
                with anyio.move_on_after(2,shield=True):
                    await c.send(p,("BaseExc",repr(exc)))
                raise


    async def work_rd(self):
        """read from MoaT-Link, send to MQTT"""
        c=self.gate.client
        d=self.data
        if d.get("dstpath",()):
            # need to start a task that monitors the node's other data
            return await self.work_rd_insert(self)
        raw = d.get("raw",False)
        
        async with t_iter(d.get("t_min",60)):
            dt = await c.cmd(Path("cl")+d["src"])
            for m in d.get("srcpath",()):
                dt=dt[m]
            if raw:
                await c.send(d["dst"],dt)
            else:
                await c.d_set(d["dst"],dt)

    async def work_rd_insert(self):
        """read from MoaT-Link, send to MQTT"""
        val = NotGiven
        c=self.gate.client
        d=self.data
        raw = d.get("raw",False)
        tm = d.get("t_min",60)

        async def mon1(evt:anyio.Event,*, task_status:anyio.abc.TaskStatus):
            async with c.monitor(d["dst"]) as mon:
                task_status.started()
                async for msg in mon:
                    val=msg.data
                    evt.set()

        async def mon2(evt:anyio.Event,*, task_status:anyio.abc.TaskStatus):
            async with c.d_watch(d["dst"]) as mon:
                task_status.started()
                async for d in mon:
                    val=d
                    evt.set()

        async with anyio.create_task_group() as tg:
            evt=anyio.Event()
            await tg.start(mon1 if raw else mon2, evt)
            with anyio.move_on_after(tm):
                await evt.wait()

            async with t_iter(tm):
                dt = await c.cmd(Path("cl")+d["src"])
                for m in d.get("srcpath",()):
                    dt=dt[m]
                if val is NotGiven:
                    val = {}
                attrdict._update(val,dpath,dt)
                if raw:
                    await c.send(d["dst"],val)
                else:
                    await c.d_set(d["dst"],val)
                
    async def restart(self):
        """
        Restart this node's task.
        """
        self.backoff=0
        self._now = True
        self.node_updated.set()


    async def run(self):
        """Run this node's transfer task."""
        if len(self.path) == 0:
            return

        while True:
            d=self.data_
            async with anyio.create_task_group() as tg:
                if self.data_ is not NotGiven:
                    await tg.start(self.work)

                await self.node_updated.wait()
                self.node_updated = anyio.Event()
                while not self._now:
                    # wait until no change
                    with anyio.move_on_after(UPDATE_TIMEOUT):
                        await self.node_updated.wait()
                        self.node_updated = anyio.Event()
                        continue
                    break
                tg.cancel_scope.cancel()
                self._now=False

@define
class Gate:
    """
    This is the manager of a subtree of transfer nodes.

    TODO: there should be some protection against running this multiple
    times. Also we want monitoring and fallback.
    """
    client:LinkCommon=field()
    path:Path=field()
    data:SingleGateNode=field(init=False,factory=SingleGateNode)

    async def run(self):
        async with anyio.create_taskgroup() as tg:
            self.data.tg = tg
            tg.start_soon(self.data.run)
            async with self.client.d_watch(self.path, subtree=True, meta=True) as mon:
                async for p,d,m in mon:
                    self.data.set(p,d,m)

