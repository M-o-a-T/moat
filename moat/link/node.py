"""
This module contains the basic MoaT-Link data model.
"""

from __future__ import annotations

import time
from logging import getLogger
from typing import Any, List

from moat.util import NotGiven, Path, attrdict, create_queue, PathShortener, PathLongener

logger = getLogger(__name__)

Key = str|int|tuple["Key"]


class Node:
    """Represents one MoaT-Link item."""

    source: str = None
    tick: int = None
    _data: Any = NotGiven
    _source: str = None

    _sub: dict = None  # sub-entries

    def __init__(self, data=NotGiven, tick=None):
        if tick is None:
            tick = 0 if data is NotGiven else time.time()
        self._data = data
        self._tick = tick

    @property
    def data(self):
        return self._data

    @property
    def tick(self):
        return self._tick

    @property
    def source(self):
        return self._source

    def __getitem__(self, item):
        """Look up the entry.

        Raises KeyError if it doesn't exist."""
        if isinstance(item,Path):
            item = item.raw
        else:
            item = (item,)
        s = self
        for n in item:
            s = s._sub[n]
        if s._data is NotGiven:
            raise KeyError(item)
        return s

    def get(self, item):
        """Look up the entry. Create if it doesn't exist."""
        s = self
        if not isinstance(item,Path):
            item = [item]
        for n in item:
            try:
                s = s._sub[n]
            except KeyError:
                s = s._add(n)
            except TypeError:
                if s._sub is not None:
                    raise
                s = s._add(n)
        return s

    def set(self, item, data, source, tick:int|None=None, force:bool=False) -> bool|None:
        """Save new data below this node.

        If @tick is earlier than the item's timestamp, always return False.
        If data changes, apply change and return True.
        If @force is not set, return False.
        Otherwise, update timestamp+source and return None.
        """
        if tick is None:
            tick = time.time()
        s = self.get(item)
        if tick <= s.tick:
            return False
        if s._data == data:
            if force:
                s._tick = tick
                s._source = source
                return None
            return False

        s._data = data
        s._tick = tick
        s._source = source
        return True

    def _add(self, item):
        if self._sub is None:
            self._sub = {}
        elif item in self._sub:
            raise ValueError("exists")
        self._sub[item] = s = Node()
        return s

    def __iter__(self):
        """
        Return a list of keys for that node.

        Used to find data from no-longer-used nodes so they can be deleted.
        """
        return self._sub.items()

    def __contains__(self, item):
        if isinstance(item,Path):
            s = self
            for n in item[:-1]:
                s = s._sub[n]
            return item[-1] in s
        return item in self._sub

    def __repr__(self):
        if self.data is NotGiven:
            return f"<{self.__class__.__name__}: - @{self.source}>" #"@{self.tick}>"
        return f"<{self.__class__.__name__}: {self.data !r} @{self.source}>" #"@{self.tick}>"

    def deleted(self) -> bool:
        """
        Check whether this tick has been marked as deleted.
        """
        return self._data is NotGiven


    async def walk(
        self, proc, max_depth=-1, min_depth=0, _depth=0, _name=Path()
    ):
        """
        Call coroutine ``proc(entry,Path)`` on this node and all its children.

        If `proc` raises `StopAsyncIteration`, chop this subtree.
        """
        todo = [(self,_name)]

        while todo:
            s,n = todo.pop()

            if min_depth <= len(n):
                try:
                    await proc(s,n)
                except StopAsyncIteration:
                    continue
            if max_depth == len(n):
                continue

            for k,v in self._sub.items():
                todo.append((v, _name/k))


    def dump(self):
        """Serialize this subtree.

        Serialization consists of a sequence of
        * prefix length (cf. .moat.util.PathShortener)
        * sub-name
        * data
        * timestamp
        * source
        * … possibly more
        """

        todo = [(self, Path())]
        ps = PathShortener()

        while todo:
            s,name = todo.pop()

            if s._data is not NotGiven:
                d,p = ps.short(name)
                yield d,p,s.data,s.tick,s.source

            if s._sub is None:
                continue
            for k,v in s._sub.items():
                todo.append((v, name/k))

    def load(self):
        """De-serialize this subtree.
        """
        pl = PathLongener()
        while True:
            d,ps,data,tick,source,*rest = yield
            item = pl.long(d,ps)
            self.set(item, data=data, source=source, tick=tick)



