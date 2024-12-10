from uasyncio.stream import Stream
from uasyncio import core as _core

async def _write(self, buf):
    # monkeypatch the stream write code
    mv = memoryview(buf)
    off = 0
    while off < len(mv):
        yield _core._io_queue.queue_write(self.s)
        ret = self.s.write(mv[off:])
        if ret is not None:
            off += ret

def _patch():
    try:
        del Stream.drain
    except AttributeError:
        pass
    else:
        Stream.write = _write

