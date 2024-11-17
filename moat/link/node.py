"""
This module contains the basic MoaT-Link data model.
"""

from __future__ import annotations

from logging import getLogger

from attrs import define, field

from moat.util import NotGiven, Path, PathLongener, PathShortener

from .meta import MsgMeta

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from typing import Any

logger = getLogger(__name__)


def _keys_repr(x):
    return ",".join(str(k) for k in x.keys())


@define
class Node:
    """Represents one MoaT-Link item."""

    _data: Any = field(init=False, default=NotGiven)
    _meta: MsgMeta | None = field(init=False, default=None)

    _sub: dict = field(init=False, factory=dict, repr=_keys_repr)  # sub-entries

    def __attrs_post_init__(self, data: Any = NotGiven, meta: MsgMeta | None = None):
        if data is not NotGiven:
            s._data = data
            s._meta = meta

    def set(self, item: Path, data: Any, meta: MsgMeta, force: bool = False) -> None:
        """Save new data below this node.

        If @tick is earlier than the item's timestamp, always return False.
        If data changes, apply change and return True.
        If @force is not set, return False.
        Otherwise, update metadata and return None.
        """
        assert isinstance(meta, MsgMeta)
        s = self.get(item)
        if s._meta is not None:
            if meta.timestamp < s._meta.timestamp:
                return False
            if s._data == data:
                if force:
                    s._meta = meta
                    return None
                return False
        s._data = data
        s._meta = meta
        return True

    @property
    def data(self) -> Any:
        if self._data is NotGiven:
            raise ValueError("empty node")
        return self._data

    def __bool__(self) -> bool:
        return self._data is not NotGiven

    @property
    def meta(self) -> MsgMeta:
        return self._meta

    def __getitem__(self, item) -> Node:
        """Look up the entry.

        Raises KeyError if it doesn't exist.
        """
        if isinstance(item, Path):
            s = self
            for k in item:
                s = s._sub[k]
        else:
            s = self._sub[item]

        if s._data is NotGiven:
            raise KeyError(item)
        return s

    def get(self, item) -> Node:
        """Look up an entry. Create if it doesn't exist."""
        if isinstance(item, Path):
            s = self
            for k in item:
                try:
                    s = s._sub[k]
                except KeyError:
                    s = s._add(k)
            return s

        try:
            return self._sub[item]
        except KeyError:
            return self._add(item)

    def _add(self, item):
        if isinstance(item, Path):
            raise ValueError("no path")
        if item in self._sub:
            raise ValueError("exists")
        self._sub[item] = s = Node()
        return s

    def __iter__(self) -> Iterator[str, Node]:
        """
        Return a list of keys under this node.
        """
        return self._sub.items()

    def __contains__(self, item) -> bool:
        if isinstance(item, Path):
            s = self
            for k in item:
                try:
                    s = s._sub[k]
                except KeyError:
                    return False
            return True

        return item in self._sub

    def deleted(self) -> bool:
        """
        Check whether this tick has been marked as deleted.
        """
        return self._data is NotGiven

    async def walk(
        self,
        proc: Callable[Awaitable[bool], [Node, Path]],
        max_depth=-1,
        min_depth=0,
        _depth=0,
        _name=Path(),
    ):
        """
        Call coroutine ``proc(entry,Path)`` on this node and all its children.

        If `proc` raises `StopAsyncIteration`, chop this subtree.
        """
        todo = [(self, _name)]

        while todo:
            s, n = todo.pop()

            if min_depth <= len(n):
                try:
                    await proc(s, n)
                except StopAsyncIteration:
                    continue
            if max_depth == len(n):
                continue

            for k, v in self._sub.items():
                todo.append((v, _name / k))

    def dump(self):
        """Serialize this subtree.

        Serialization consists of a sequence of
        * prefix length (cf. .moat.util.PathShortener)
        * sub-path
        * data
        * meta
        """

        todo = [(self, Path())]
        ps = PathShortener()

        while todo:
            s, name = todo.pop()

            if s:
                d, p = ps.short(name)
                yield d, p, s._data, s._meta

            if s._sub is None:
                continue
            for k, v in s._sub.items():
                todo.append((v, name / k))

    def load(self):
        """De-serialize this subtree."""
        pl = PathLongener()
        while True:
            d, ps, data, meta, *rest = yield
            item = pl.long(d, ps)
            self.set(item, data=data, meta=meta)
