from sys import print_exception as print_exc
from uasyncio import Event,sleep,TimeoutError, run as _run, create_task as _create_task, CancelledError
from utime import ticks_ms, ticks_add, ticks_diff

async def wait_for_ms(timeout,p,*a,**k):
    """
        uasyncio.wait_for_ms() but with sane calling convention
    """
    return await uasyncio.wait_for_ms(p(*a,**k),timeout)

async def spawn(evt,p,*a,**k):
    async def catch():
        try:
            return await p(*a,**k)
        except CancelledError:
            raise
        except Exception as exc:
            print_exc(exc)
            raise
        finally:
            if evt is not None:
                evt.set()

    return _create_task(catch())

def run(p,*a,**k):
    return _run(p(*a,**k))

