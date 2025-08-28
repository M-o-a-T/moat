import threading
from typing import Dict, Hashable, List, Optional, Tuple, Union

try:
    from collections.abc import MutableMapping
except ImportError:
    from collections import MutableMapping

# ==== Centralized type aliases ====
Priority = Union[int, float]
Key = Hashable
InitialData = Optional[Dict[Key, Priority]]
HeapItem = List[Union[Key, Priority]]  # Each heap item is [key, priority]
PriorityType = (int, float)

class HeapMap(MutableMapping):
    """
    A thread-safe heap that behaves like a dict but maintains heap ordering.

    Supports both min-heap and max-heap modes, dictionary-like access, key updates,
    removals, bulk initialization, and safe iteration (detects concurrent modifications).
    """

    def __init__(self, initial: InitialData = None, is_max_heap: bool = False):
        """
        Initialize the HeapDict.

        :param initial: Optional mapping of keys to initial priorities.
        :param is_max_heap: If True, treat as a max-heap; otherwise a min-heap.
        :raises TypeError: If any priority in `initial` is not an int or float.
        """
        self.heap: List[HeapItem] = []
        self.position: Dict[Key, int] = {}
        self.lock = threading.Lock()
        # Comparison function determines min or max behavior
        self.compare = (lambda x, y: x < y) if not is_max_heap else (lambda x, y: x > y)

        # Bulk initialize if provided
        if initial:
            for key, priority in initial.items():
                if not isinstance(priority, PriorityType):
                    raise TypeError(f"Priority for key '{key}' must be int or float.")
                self.heap.append([key, priority])
            # Record positions and heapify
            for idx, (key, _) in enumerate(self.heap):
                self.position[key] = idx
            for i in reversed(range(len(self.heap) // 2)):
                self._sift_down(i)

    def items(self):
        """
        Yield (key, priority) pairs.
        """
        return self._create_iterator(True, True)

    def keys(self):
        """
        Yield keys only.
        """
        return self._create_iterator(True, False)

    def values(self):
        """
        Yield priorities only.
        """
        return self._create_iterator(False, True)

    def popitem(self) -> Tuple[Key, Priority]:
        """
        Remove and return root (min or max) item.

        :return: (key, priority)
        :raises IndexError: If empty.
        """
        with self.lock:
            if not self.heap:
                raise IndexError("popitem from empty heap")
            key, prio = self.heap[0]
            last = self.heap.pop()
            if self.heap:
                self.heap[0] = last
                self.position[last[0]] = 0
                self._sift_down(0)
            del self.position[key]
            return key, prio

    def peekitem(self) -> Tuple[Key, Priority]:
        """
        Return root item without removing it.

        :raises IndexError: If empty.
        """
        with self.lock:
            if not self.heap:
                raise IndexError("peekitem from empty heap")
            return self.heap[0][0], self.heap[0][1]

    def update(self, key: Key, new_priority: Priority) -> None:
        """
        Update priority for existing key and reheapify.

        :param key: Key to update.
        :param new_priority: New priority value.
        :raises KeyError: If key not found.
        :raises TypeError: If new_priority invalid.
        """
        with self.lock:
            if key not in self.position:
                raise KeyError(f"Key {key} not found in heap.")
            if not isinstance(new_priority, PriorityType):
                raise TypeError("New priority must be int or float.")
            idx = self.position[key]
            old = self.heap[idx][1]
            self.heap[idx][1] = new_priority
            if self.compare(new_priority, old):
                self._sift_up(idx)
            else:
                self._sift_down(idx)

    def clear(self) -> None:
        """
        Remove all items from the heap.
        """
        with self.lock:
            self.heap.clear()
            self.position.clear()

    def is_empty(self) -> bool:
        """
        Check whether heap is empty.

        :return: True if no items.
        """
        with self.lock:
            return not self.heap

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
            if self.compare(self.heap[idx][1], self.heap[parent][1]):
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

            if left < n and self.compare(self.heap[left][1], self.heap[best][1]):
                best = left
            if right < n and self.compare(self.heap[right][1], self.heap[best][1]):
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
        with self.lock:
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
        with self.lock:
            if not isinstance(priority, PriorityType):
                raise TypeError("Priority must be int or float.")
            if key in self.position:
                self.update(key, priority)
            else:
                idx = len(self.heap)
                self.heap.append([key, priority])
                self.position[key] = idx
                self._sift_up(idx)

    def __delitem__(self, key: Key) -> None:
        """
        Remove `key` from the heap.

        :param key: Key to remove.
        :raises KeyError: If `key` not present.
        """
        with self.lock:
            if key not in self.position:
                raise KeyError(f"Key {key} not found in heap.")
            idx = self.position.pop(key)
            last = self.heap.pop()
            if idx < len(self.heap):
                self.heap[idx] = last
                self.position[last[0]] = idx
                self._sift_down(idx)
                self._sift_up(idx)

    def __contains__(self, key: Key) -> bool:
        """
        Check if `key` exists in the heap.
        """
        with self.lock:
            return key in self.position

    def __len__(self) -> int:
        """
        Return number of items.
        """
        with self.lock:
            return len(self.heap)

    def __str__(self) -> str:
        """
        String representation: list of {key: priority}.
        """
        with self.lock:
            return "[" + ", ".join(f"{{{k}: {v}}}" for k, v in self.heap) + "]"

    def _create_iterator(self, return_keys=True, return_values=True):
        """
        Internal: return iterator over keys, values, or items, detecting concurrent mods.

        :param return_keys: Yield keys if True.
        :param return_values: Yield priorities if True.
        """
        with self.lock:
            self._iterator_state = {
                "index": 0,
                "heap_len": len(self.heap),
                "mutations_detected": False,
                "current_position": self.position.copy(),
            }

        class SafeIterator:
            def __init__(self, heap_dict, return_keys, return_values):
                self.heap_dict = heap_dict
                self.state = heap_dict._iterator_state
                self.return_keys = return_keys
                self.return_values = return_values

            def __iter__(self):
                return self

            def __next__(self):
                s = self.state
                if s["index"] < s["heap_len"]:
                    key, prio = self.heap_dict.heap[s["index"]]
                    s["index"] += 1
                    with self.heap_dict.lock:
                        if s["current_position"] != self.heap_dict.position:
                            s["mutations_detected"] = True
                    if s["mutations_detected"]:
                        raise RuntimeError("Modification detected during iteration.")
                    out = []
                    if self.return_keys: out.append(key)
                    if self.return_values: out.append(prio)
                    return tuple(out) if len(out)>1 else out[0]
                raise StopIteration

        return SafeIterator(self, return_keys, return_values)

    def __iter__(self):
        """
        Iterate over (key, priority) pairs.
        """
        return self._create_iterator(True, True)
