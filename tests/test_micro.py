"""
Basic test using a MicroPython subtask
"""
import os
import sys
import anyio
from contextlib import asynccontextmanager

from moat.micro.compat import TaskGroup
from moat.util import attrdict
from moat.micro.main import get_link_serial
from moat.micro.proto.multiplex import Multiplexer

async def _test(tp):
    try:
        os.stat("micro/lib")
    except OSError:
        pre=""
    else:
        pre="micro/"

    argv=[pre+"lib/micropython/ports/unix/build-standard/micropython",pre+"tests-mpy/mplex.py", str(tp)]


    @asynccontextmanager
    async def factory(req):
        obj = attrdict()
        obj.debug=True
        obj.reliable=False
        obj.guarded=False
        async with await anyio.open_process(argv, stderr=sys.stderr) as proc:
            ser = anyio.streams.stapled.StapledByteStream(proc.stdin, proc.stdout)
            async with get_link_serial(obj, ser, request_factory=req, log=True, reliable=True) as link:
                yield link

    mplex = Multiplexer(factory, tp / "moat" ,{}, fatal=True)
    async with TaskGroup() as tg:
        srv = await tg.spawn(mplex.serve, load_cfg=True)
        with anyio.fail_after(3):
            await mplex.wait()
        # TODO test stuff
        print("TEST")
        await anyio.sleep(1)
        srv.cancel()


def test_micro(tmp_path):
    """
    Talk to a MicroPython task
    """
    anyio.run(_test, tmp_path, backend="trio")

