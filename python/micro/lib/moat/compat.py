from usys import print_exception as print_exc
import uasyncio
from uasyncio import Event,Lock,Queue,sleep,sleep_ms,TimeoutError, run as _run, TaskGroup as _tg, CancelledError
from utime import ticks_ms, ticks_add, ticks_diff

async def idle():
    while True:
        await sleep(60*60*12)  # half a day

async def wait_for(timeout,p,*a,**k):
    """
        uasyncio.wait_for() but with sane calling convention
    """
    return await uasyncio.wait_for(p(*a,**k),timeout)

async def wait_for_ms(timeout,p,*a,**k):
    """
        uasyncio.wait_for_ms() but with sane calling convention
    """
    return await uasyncio.wait_for_ms(p(*a,**k),timeout)

class TaskGroup(_tg):
    async def spawn(self, p, *a, **k):
        return self.create_task(p(*a,**k))

def run(p,*a,**k):
    return _run(p(*a,**k))

async def run_server(*a, **kw):
    from uasyncio import run_server as rs
    return await rs(*a,**kw)
