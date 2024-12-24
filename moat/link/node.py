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
    from collections.abc import Iterator

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
            self._data = data
            self._meta = meta

    def set(self, item: Path, data: Any, meta: MsgMeta, force: bool = False) -> None:
        """Save new data below this node.

        If @tick is earlier than the item's timestamp, always return False.
        If data changes, apply change and return True.
        If @force is not set, return False.
        Otherwise, update metadata and return None.
        """
        assert isinstance(meta, MsgMeta)
        s = self.get(item)
        if s._meta is not None:  # noqa:SLF001
            if meta.timestamp < s._meta.timestamp:  # noqa:SLF001
                return False
            if s._data == data:  # noqa:SLF001
                if force:
                    s._meta = meta  # noqa:SLF001
                    return None
                return False
        s._data = data  # noqa:SLF001
        s._meta = meta  # noqa:SLF001
        return True

    @property
    def data(self) -> Any:
        "return current data"
        if self._data is NotGiven:
            raise ValueError("empty node")
        return self._data

    def keys(self):
        return self._sub.keys()

    def items(self):
        return self._sub.items()

    def __bool__(self) -> bool:
        "check if data exist"
        return self._data is not NotGiven

    def dump(self):
        """
        Iterator that returns a serialization of this node tree.

        TODO: try not to allocate a mountain of paths.
        """
        ps = PathShortener()
        for p, d, m in self._dump(
            (),
        ):
            s, p = ps.short(p)
            yield s, p, d, m

    def dump2(self):
        yield from self._dump2((), 0)

    def _dump(self, path):
        if self._data is not NotGiven:
            yield path, self._data, self._meta
        for k, v in self._sub.items():
            yield from v._dump(
                path + (k,),
            )

    def _dump2(self, path, level):
        if self._data is not NotGiven:
            yield level, path, self._data, self._meta
            level += len(path)
            path = ()
        for k, v in self._sub.items():
            if path:
                it = iter(v._dump2(path + (k,), level))
                try:
                    d = next(it)
                except StopIteration:
                    pass
                else:
                    level += len(path)
                    path = ()
                    yield from it

    def load(self, force=False):
        """
        receives a data stream created by `dump`.

        if @force is set, overwrite existing data even if newer.
        """
        pl = PathLongener()
        while True:
            s, p, d, m = yield
            p = pl.long(s, p)
            n = self.get(p)
            if force or n.meta is None or n.meta.timestamp < m.timestamp:
                n._data = d
                n._meta = m

    @property
    def meta(self) -> MsgMeta:
        "return current metadata"
        return self._meta

    def __getitem__(self, item) -> Node:
        """Look up the entry.

        Raises KeyError if it doesn't exist.
        """
        if isinstance(item, Path):
            s = self
            for k in item:
                s = s._sub[k]  # noqa:SLF001
        else:
            s = self._sub[item]

        if s._data is NotGiven:  # noqa:SLF001
            raise KeyError(item)
        return s

    def get(self, item) -> Node:
        """Look up an entry. Create if it doesn't exist."""
        if isinstance(item, Path):
            s = self
            for k in item:
                try:
                    s = s._sub[k]  # noqa:SLF001
                except KeyError:
                    s = s._add(k)  # noqa:SLF001
            return s

        try:
            return self._sub[item]
        except KeyError:
            return self._add(item)

    def _add(self, item):
        if isinstance(item, Path):
            raise TypeError("no path")
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
                    s = s._sub[k]  # noqa:SLF001
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
        proc: Callable[Awaitable[bool], [Path, Node]],
        max_depth=-1,
        min_depth=0,
        timestamp=0,
        _depth=0,
        _name=Path(),  # noqa:B008
    ):
        """
        Call coroutine ``proc(entry,Path)`` on this node and all its children.

        If `proc` raises `StopAsyncIteration`, chop this subtree.
        """
        todo = [(_name, self)]

        while todo:
            s, p = todo.pop()

            if min_depth <= len(p) and s.meta.timestamp >= timestamp:
                try:
                    await proc(p, s)
                except StopAsyncIteration:
                    continue
            if max_depth == len(p):
                continue

            for k, v in self._sub.items():
                todo.append((_name / k, v))
