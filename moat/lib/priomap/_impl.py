"""
Priority mapping library
"""

from __future__ import annotations

import anyio
from time import monotonic as time

try:
    from collections.abc import MutableMapping
except ImportError:
    from collections.abc import MutableMapping

from typing import TYPE_CHECKING, TypeVar, overload

if TYPE_CHECKING:
    from abc import abstractmethod
    from types import EllipsisType

    from collections.abc import Hashable, Iterator
    from typing import Protocol

    class Comparable(Protocol):
        """Protocol for annotating comparable types."""

        @abstractmethod
        def __lt__(self: CT, other: CT, /) -> bool: ...

    CT = TypeVar("CT", bound=Comparable)
    RT = TypeVar("RT")

    Priority = CT
    Key = Hashable
    InitialData = dict[Key, Priority] | None
    InitialPrio = dict[Key, float] | None
    HeapItem = list[Key | Priority]  # Each heap item is [key, priority]

__all__ = ["PrioMap", "TimerMap"]


class PrioMap(MutableMapping):
    """
    A heap that behaves like a dict but maintains heap ordering.

    Supports dictionary-like access, key updates,
    removals, bulk initialization, and safe iteration (detects concurrent modifications).
    """

    def __init__(self, initial: InitialData = None):
        """
        Initialize the HeapDict.

        :param initial: Optional mapping of keys to initial priorities.
        :raises TypeError: If any priority in `initial` is not an int or float.
        """
        self.heap: list[HeapItem] = []
        self.position: dict[Key, int] = {}
        self.evt: anyio.Event = anyio.Event()

        # Bulk initialize if provided
        if initial:
            self.bulk(initial.items())

    def bulk(self, initial: Iterator[HeapItem]):
        """
        Bulk insert.
        """
        for key, priority in initial:
            self.heap.append([key, priority])
        # Record positions and heapify
        for idx, (key, _) in enumerate(self.heap):
            self.position[key] = idx
        for i in reversed(range(len(self.heap) // 2)):
            self._sift_down(i)

    def items(self):
        """
        Yield (key, priority) pairs.

        Items are heap sorted, i.e. the first result is guaranteed to have
        the lowest priority, but after that it's anybody's guess.
        """
        return self._create_iterator(None)

    def keys(self):
        """
        Yield keys only.

        Items are heap sorted, i.e. the first key is guaranteed to have
        the lowest priority, but after that it's anybody's guess.
        """
        return self._create_iterator(True)

    def values(self):
        """
        Yield priorities only.

        Items are heap sorted, i.e. the first priority is guaranteed to be
        lowest, but after that it's anybody's guess.
        """
        return self._create_iterator(False)

    @overload
    def pop(self) -> tuple[Key, Priority]: ...

    @overload
    def pop(self, key: Key) -> Priority: ...

    @overload
    def pop(self, key: Key, default: RT) -> Priority | RT: ...

    def pop(self, *a):
        """
        Remove and return an item.

        Args are passed to dict.pop.

        :return: (key, priority)
        :raises IndexError: If empty.
        """
        if a:
            if len(a) > 2:
                raise TypeError("PrioMap.pop([key[,default]])")
            try:
                pos = self.position[a[0]]
            except KeyError:
                if len(a) > 1:
                    return a[1]
                raise
        else:
            pos = 0

        key, prio = self.heap[pos]

        last = self.heap.pop()
        if pos < len(self.heap):
            self.heap[pos] = last
            self.position[last[0]] = 0
            self._sift_down(pos)
        del self.position[key]
        if a:
            return prio
        return key, prio

    def peek(self) -> tuple[Key, Priority]:
        """
        Return the root item without removing it.

        :raises IndexError: If empty.
        """
        try:
            return self.heap[0][0], self.heap[0][1]
        except IndexError:
            raise IndexError("Queue is empty") from None

    def update(self, key: Key, new_priority: Priority) -> None:
        """
        Update priority for an existing key, then reheapify.

        :param key: Key to update.
        :param new_priority: New priority value.
        :raises KeyError: If key not found.
        :raises TypeError: If new_priority invalid.
        """
        if key not in self.position:
            raise KeyError(f"Key {key} not found in heap.")
        idx = self.position[key]
        old = self.heap[idx][1]
        self.heap[idx][1] = new_priority
        if new_priority < old:
            self._sift_up(idx)
        else:
            self._sift_down(idx)

        if idx == 0 or self.heap[0][0] == key:
            self.evt.set()
            self.evt = anyio.Event()

    def clear(self) -> None:
        """
        Remove all items from the heap.
        """
        self.heap.clear()
        self.position.clear()
        self.evt.set()
        self.evt = anyio.Event()

    def is_empty(self) -> bool:
        """
        Check whether heap is empty.

        :return: True if no items.
        """
        return not self.heap

    def __bool__(self) -> bool:
        """
        Check whether heap is not empty.

        :return: False if no items.
        """
        return bool(self.heap)

    def _swap(self, i: int, j: int) -> None:
        """
        Swap elements at indices `i` and `j` and update their positions.
        """
        self.heap[i], self.heap[j] = self.heap[j], self.heap[i]
        self.position[self.heap[i][0]] = i
        self.position[self.heap[j][0]] = j

    def _sift_up(self, idx: int) -> None:
        """
        Sift element at index `idx` up until heap property is restored.
        """
        while idx > 0:
            parent = (idx - 1) // 2
            if self.heap[idx][1] < self.heap[parent][1]:
                self._swap(idx, parent)
                idx = parent
            else:
                break

    def _sift_down(self, idx: int) -> None:
        """
        Sift element at index `idx` down until heap property is restored.
        """
        n = len(self.heap)
        while True:
            left = 2 * idx + 1
            right = 2 * idx + 2
            best = idx

            if left < n and self.heap[left][1] < self.heap[best][1]:
                best = left
            if right < n and self.heap[right][1] < self.heap[best][1]:
                best = right

            if best != idx:
                self._swap(idx, best)
                idx = best
            else:
                break

    def __getitem__(self, key: Key) -> Priority:
        """
        Get the priority for `key`.

        :param key: Key to look up.
        :return: Associated priority.
        :raises KeyError: If `key` is not present.
        """
        if key in self.position:
            return self.heap[self.position[key]][1]
        raise KeyError(f"Key {key} not found in heap.")

    def __setitem__(self, key: Key, priority: Priority) -> None:
        """
        Insert or update `key` with `priority`.

        :param key: Key to insert/update.
        :param priority: Priority value (int or float).
        :raises TypeError: If `priority` is not int or float.
        """
        if key in self.position:
            self.update(key, priority)
        else:
            idx = len(self.heap)
            self.heap.append([key, priority])
            self.position[key] = idx
            self._sift_up(idx)
            if self.heap[0][0] == key:
                self.evt.set()
                self.evt = anyio.Event()

    def __delitem__(self, key: Key) -> None:
        """
        Remove `key` from the heap.

        :param key: Key to remove.
        :raises KeyError: If `key` not present.
        """
        if key not in self.position:
            raise KeyError(f"Key {key} not found in heap.")
        idx = self.position.pop(key)
        last = self.heap.pop()
        if idx < len(self.heap):
            self.heap[idx] = last
            self.position[last[0]] = idx
            self._sift_down(idx)
            self._sift_up(idx)
            if idx == 0:
                self.evt.set()
                self.evt = anyio.Event()

    def __contains__(self, key: Key) -> bool:
        """
        Check if `key` exists in the heap.
        """
        return key in self.position

    def __len__(self) -> int:
        """
        Return number of items.
        """
        return len(self.heap)

    def __str__(self) -> str:
        """
        String representation: list of {key: priority}.
        """
        return "[" + ", ".join(f"{{{k}: {v}}}" for k, v in self.heap) + "]"

    def _create_iterator(self, keys: bool | None = None):
        """
        Internal: return iterator over keys, values, or items, detecting concurrent mods.

        :param keys: Yield keys if True, values if False, both if None
        """
        self._iterator_state = {
            "index": 0,
            "len": len(self.heap),
            "pos": self.position.copy(),
        }

        class SafeIterator:
            def __init__(self, heap_dict, keys):
                self.heap_dict = heap_dict
                self.state = heap_dict._iterator_state  # noqa: SLF001
                self.keys = keys

            def __iter__(self):
                return self

            def __next__(self):
                s = self.state
                if s["index"] < s["len"]:
                    key, prio = self.heap_dict.heap[s["index"]]
                    s["index"] += 1
                    if s["pos"] != self.heap_dict.position:
                        raise RuntimeError("Modification detected during iteration.")
                    if self.keys:
                        return key
                    if self.keys is False:
                        return prio
                    return (key, prio)
                raise StopIteration

        return SafeIterator(self, keys)

    def __iter__(self):
        """
        Iterate over (key, priority) pairs.

        The contents are *not* consumed.
        """
        return self._create_iterator(None)

    def __aiter__(self):
        """
        Iterate asynchronously over (key, priority) pairs.

        Contents are consumed.
        """
        return self

    async def __anext__(self) -> tuple[Key, Priority]:
        """
        Return the lowest-priority item.

        Waits for the next item if the heap is empty.
        """
        while not self.heap:
            await self.evt.wait()
        return self.pop()

    async def apeek(self) -> tuple[Key, Priority]:
        """
        Return the root item without removing it.

        Waits for an item to arrive if the heap is empty.
        """
        while not self.heap:
            await self.evt.wait()
        return self.heap[0][0], self.heap[0][1]


class TimerMap:
    """
    A map that stores timeout values.

    The value auto-decrements; async iteration returns a key
    when its timer expires.

    Timeouts can be retrieved and updated iff they have not been processed.
    Negative delays are not an error.
    """

    def __init__(self, initial: InitialPrio = None):
        self._pm = PrioMap()
        if initial:
            self._pm.bulk((k, self.T_ADD(v)) for k, v in initial.items())

    @staticmethod
    def T_ADD(p):
        "Add the current time."
        return p + time()

    @staticmethod
    def T_SUB(p):
        "Subtract the current time."
        return p - time()

    def __setitem__(self, key: Key, delay: float) -> None:
        self._pm[key] = self.T_ADD(delay)

    def __getitem__(self, key: Key) -> float:
        return self.T_SUB(self._pm[key])

    def __delitem__(self, key: Key) -> float:
        del self._pm[key]

    async def apeek(self) -> tuple[Key, float]:
        """
        Return the first item (without removing it).

        Waits while the heap is empty.
        """
        k, p = await self._pm.apeek()
        return k, self.T_SUB(p)

    def __len__(self):
        return len(self._pm)

    def __aiter__(self):
        return self

    async def __anext__(self) -> Key:
        "iterate keys as they time out."
        while True:
            k, p = await self.apeek()
            if p > 0:
                with anyio.move_on_after(p):
                    await self._pm.evt.wait()
            else:
                k, p = self.pop()
                if p > 0:
                    raise RuntimeError("Heap got confused? {k !r}:{p}")
                return k

    def update(self, key: Key, new_delay: float) -> None:
        """
        Update priority for an existing key, then reheapify.
        """
        self._pm.update(key, self.T_ADD(new_delay))

    @overload
    def pop(self) -> tuple[Key, float]: ...

    @overload
    def pop(self, key: Key) -> float: ...

    def pop(self, a: Key | EllipsisType = Ellipsis):
        """
        Remove and return an item.

        Args are passed to dict.pop.

        :return: (key, priority)
        :raises IndexError: If empty.
        """
        if a is Ellipsis:
            key, prio = self._pm.pop()
            return key, self.T_SUB(prio)
        else:
            return self.T_SUB(self._pm.pop(a))
