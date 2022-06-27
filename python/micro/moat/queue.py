__all__ = ('Queue', 'QueueFull', 'QueueEmpty')
        #'PriorityQueue', 'LifoQueue',

from uasyncio import core
from collections import deque

class QueueEmpty(Exception):
    """Raised when Queue.get_nowait() is called on an empty Queue."""
    pass

class QueueClosed(RuntimeError):
    """Raised when getting from/putting to a closed queue."""
    pass

class QueueFull(Exception):
    """Raised when the Queue.put_nowait() method is called on a full Queue."""
    pass

class Queue:
    """A queue, useful for coordinating producer and consumer coroutines.

    If maxsize is less than zero, the queue size is infinite. If it
    is an integer greater than 0, then "await put()" will block when the
    queue reaches maxsize, until an item is removed by get(). A size-zero
    queue acts like a rendez-vous point, i.e. "await get()" will block
    until the corresponding "await put()" runs, or vice versa.
    """

    def __init__(self, maxsize=0):
        self._maxsize = maxsize

        self._getters = core.TaskQueue()
        self._putters = core.TaskQueue()
        self._getdata = dict()  # task > [item]
        self._putdata = dict()  # task > item

        self._init(maxsize)

    def _init(self, maxsize):
        self._queue = deque()

    def _get(self):
        return self._queue.popleft()

    def _put(self, item):
        self._queue.append(item)

    def _wakeup_next(self, waiting):
        # Wake up the next waiter, if any
        if waiting.peek():
            t = waiting.pop()
            core._task_queue.push(t)
            return t

    def __repr__(self):
        return f'<{type(self).__name__} at {id(self):#x} {self._format()}>'

    def __str__(self):
        return f'<{type(self).__name__} {self._format()}>'

    def _format(self):
        result = f'maxsize={self._maxsize!r}'
        if getattr(self, '_queue', None):
            result += f' _queue={list(self._queue)!r}'
        if self._getters:
            result += f' _get[{len(self._getters)}]'
        if self._putters:
            result += f' _put[{len(self._putters)}]'
        return result

    def qsize(self):
        """Number of items in the queue."""
        return len(self._queue)

    @property
    def maxsize(self):
        """Number of items allowed in the queue."""
        return self._maxsize

    def empty(self):
        """Return True if the queue is empty, i.e.
        calling get_nowait would throw an exception.
        """
        if self._maxsize == 0:
            # We'd block if there is no waiting setter
            return not self._putters.peek()
        return self.qsize() == 0

    def full(self):
        """Return True if the queue is full, i.e.
        calling put_nowait would throw an exception.
        """
        if self._maxsize < 0:
            return False
        elif self._maxsize == 0:
            # We'd block if there is no waiting getter
            return not self._getters.peek()
        else:
            return self.qsize() >= self._maxsize

    async def put(self, item):
        """Put an item into the queue.

        If the queue is full, wait until a free slot is available before
        adding the item.
        """
        try:
            self.put_nowait(item)
        except QueueFull:
            t = core.cur_task
            self._putdata[t] = item
            self._putters.push(t)
            t.data = self._putters
            try:
                yield
            except:
                self._putdata.pop(t, None)
                raise
            if t in self._putdata:
                del self._putdata[t]
                raise QueueClosed


    def put_nowait(self, item):
        """Put an item into the queue without blocking.

        If no free slot is immediately available, raise QueueFull.
        """
        if self._closed:
            raise QueueClosed

        t = self._wakeup_next(self._getters)
        if t:
            self._getdata[t].append(item)
        elif self._maxsize < 0 or len(self._queue) < self._maxsize:
            self._queue.append(item)
        else:
            raise QueueFull


    async def get(self):
        """Get an item from the queue.

        If the queue is empty, wait until an item is available.
        """
        try:
            return self.get_nowait()
        except QueueEmpty:
            c = []
            t = core.cur_task
            self._getdata[t] = c
            self._getters.push(t)
            try:
                yield
            except core.CancelledError:
                if not c:
                    raise
            finally:
                self._getdata.pop(t, None)
            if c:
                return c[0]
            raise QueueClosed


    def get_nowait(self):
        """Remove and return an item from the queue.

        If no item is available, raise QueueEmpty.
        """
        if self._closed:
            raise QueueClosed

        t = self._wakeup_next(self._putters)
        if t:
            item = self._putdata.pop(t)
            self._queue.append(item)
        if len(self._queue):
            return self._queue.popleft()
        else:
            raise QueueEmpty


    def close(self):
        self._closed = True
        while True:
            t = self._wakeup_next(self._getters)
            if t is None:
                break
        while True:
            t = self._wakeup_next(self._putters)
            if t is None:
                break
