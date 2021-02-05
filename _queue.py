from anyio import create_memory_object_stream as _cmos

__all__ = ["Queue", "create_queue"]


class Queue:
    def __init__(self, length=0):
        self._s, self._r = _cmos(length)

    def put(self, x):
        return self._s.send(x)

    def get(self):
        return self._r.receive()

    def qsize(self):
        return len(self._s._state.buffer)  # ugh

    def empty(self):
        return not len(self._s._state.buffer)  # ugh

    def __aiter__(self):
        return self

    def __anext__(self):
        return self._r.__anext__()

    def close_sender(self):
        return self._s.aclose()

    def close_receiver(self):
        return self._r.aclose()


def create_queue(length=0):
    return Queue(length)
