"""
This module contains the basic MoaT-Link data model.
"""

from __future__ import annotations

from logging import getLogger

from attrs import define, field

from moat.util import NotGiven, Path, PathLongener, PathShortener
from moat.util.exc import ExpKeyError

from ..meta import MsgMeta

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterator
    from typing import Any
    from moat.lib.cmd import Key

logger = getLogger(__name__)


def _keys_repr(x):
    return ",".join(str(k) for k in x)


@define
class Node:
    """Represents one MoaT-Link item."""

    _data: Any = field(init=False, default=NotGiven)
    _meta: MsgMeta | None = field(init=False, default=None)

    _sub: dict[Key,Node] = field(init=False, factory=dict, repr=_keys_repr)  # sub-entries

    def __attrs_post_init__(self, data: Any = NotGiven, meta: MsgMeta | None = None):
        if data is not NotGiven:
            self._data = data
            self._meta = meta

    def set(self, item: Path, data: Any, meta: MsgMeta, force: bool = False) -> bool | None:
        """Save new data below this node.

        If @tick is earlier than the item's timestamp, always return False.
        If data changes, apply change and return True.
        If @force is not set, return False.
        Otherwise, update metadata and return None.
        """
        assert isinstance(meta, MsgMeta)
        s = self.get(item)
        if s._meta is not None:  # noqa:SLF001
            if meta.timestamp <= s._meta.timestamp:  # noqa:SLF001
                return False
            if not force and s._data == data:  # noqa:SLF001
                return None
        s.set_(item,data,meta)
        return True

    def set_(self, path:Path, data:Any, meta:MsgMeta):
        "Low-level node data setter. The (sub)path is not stored by default."
        self._data = data
        self._meta = meta

    @property
    def data(self) -> Any:
        "return current data, raises ValueError if empty"
        if self._data is NotGiven:
            raise ValueError("empty node")
        return self._data

    @property
    def data_(self) -> Any:
        "return current data, returns NotGiven if empty"
        return self._data

    def keys(self):
        return self._sub.keys()

    def items(self):
        return self._sub.items()

    def __bool__(self) -> bool:
        "check if data exist"
        return self._data is not NotGiven

    def __eq__(self, other):
        if self._data != other._data:
            return False
        if self._sub != other._sub:
            return False
        return True

    def _dump_x(self):
        # Iterator that returns a serialization of this node tree.
        ps = PathShortener()
        for p, d, m in self._dump_x_(()):
            s, p = ps.short(p)
            yield (s, p, d, *(m.dump() if m is not None else ()))

    def _dump_x_(self, path):
        # Helper for _dump_x
        if self._data is not NotGiven:
            yield path, self._data, self._meta
        for k, v in self._sub.items():
            yield from v._dump_x_(
                path + (k,),
            )

    def dump(self):
        """
        An iterator that returns a path-shortened serialization of this
        node tree.
        """
        # The naïve method (in `_dump_x`) creates a full-path tuple for
        # each node, all of which the PathShortener will throw away.
        #
        # This code yields the exact same data – without that overhead.
        # The old code is kept (a) because it's more easily understood,
        # (b) for unit testing.

        yield from self._dump((), 0)

    def _dump(self, path, level):
        if self._data is not NotGiven:
            yield (level, path, self._data, *(self._meta.dump() if self._meta is not None else ()))
            level += len(path)
            path = ()
        for k, v in self._sub.items():
            it = iter(v._dump(path + (k,), level))
            try:
                d = next(it)
            except StopIteration:
                pass
            else:
                yield d
                level += len(path)
                path = ()
                yield from it

    def load(self, force=False):
        """
        receives a data stream created by `dump`.

        if @force is set, overwrite existing data even if newer.
        """
        # TODO mirror dump() and do this without a PathLongener
        pl = PathLongener()
        while True:
            s, p, d, *m = yield
            m = MsgMeta.restore(m, NotGiven)
            p = pl.long(s, p)
            n = self.get(p)
            if force or n.meta is None or n.meta.timestamp < m.timestamp:
                n._data = d
                n._meta = m

    @property
    def meta(self) -> MsgMeta|None:
        "return current metadata"
        return self._meta

    @meta.deleter
    def meta(self) -> None:
        "Clear metadata"
        del self._meta

    def __delitem__(self, item) -> None:
        """
        Remove an item. (It must be empty.)

        **Warning** Don't call this unless the timeout for deletion has passed.
        """
        d = self._sub[item]

        if d._sub or d.data is not NotGiven:
            raise ValueError(item)
        del self._sub[item]

    def __getitem__(self, item) -> Node:
        """Look up the entry.

        Raises KeyError if it doesn't exist.
        """
        if isinstance(item, Path):
            s = self
            for k in item:
                try:
                    s = s._sub[k]  # noqa:SLF001
                except KeyError:
                    raise ExpKeyError(k)
        else:
            s = self._sub[item]

        if s._data is NotGiven:  # noqa:SLF001
            raise ExpKeyError(item)
        return s

    def get(self, item, create=None) -> Node:
        """Look up an entry. Create if it doesn't exist.

        Unlike data[key], an "empty" key is not an error.
        """
        if item is Ellipsis:
            return self

        if isinstance(item, Path):
            s = self
            for n, k in enumerate(item):
                if isinstance(k, Path):
                    # import traceback
                    # logger.warning("Looking up %r\n%s", item, ''.join(traceback.format_stack()))
                    logger.warning("Looking up %r\n", item)
                    s = s.get(k, create=create)
                    continue
                try:
                    s = s._sub[k]  # noqa:SLF001
                except KeyError:
                    if create is False:
                        raise
                    s = s._add(k)  # noqa:SLF001
                else:
                    if create is True and n == len(item) - 1 and s._data is not NotGiven:
                        raise KeyError(k)
            return s

        try:
            res = self._sub[item]
        except KeyError:
            if create is False:
                raise
            return self._add(item)
        else:
            if create is True and res._data is not NotGiven:
                raise KeyError(item)
            return res

    def _add(self, item):
        if item in self._sub:
            raise ValueError("exists")
        self._sub[item] = s = type(self)()
        return s

    def __iter__(self) -> Iterator[tuple[Key, Node]]:
        """
        Return a list of keys under this node.
        """
        return iter(self._sub.items())

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
        proc: Callable[[Path, Node], Awaitable[bool|None]],
        max_depth: int = 999999,
        min_depth: int = 0,
        timestamp: int | float = 0,
        depth_first: bool = False,
        force: bool = False,
    ):
        """
        Calls coroutine ``proc(node,Subpath)`` on this node and all its children.

        Deleted nodes are passed if they still have a Meta entry.

        if @depth_first is not set and @proc explicitly returns False,
        the subtree is skipped.

        if @force is set, also visit empty nodes.
        """

        async def _walk(s, p):
            if depth_first and max_depth > len(p):
                for k, v in s._sub.items():
                    await _walk(v, p / k)

            if min_depth <= len(p) and (force or (s.meta is not None and s.meta.timestamp >= timestamp)):
                if await proc(p, s) is False:
                    return

            if not depth_first and max_depth > len(p):
                for k, v in list(s._sub.items()):
                    await _walk(v, p / k)

        await _walk(self, Path())


    def search(self, path:Path) -> Node:
        """
        Find the destination node of a path, including wildcards.
        """
        nf = NodeFinder(self)
        for elem in path:
            nf.step(elem)
        return nf.result


class NodeFinder:
    """A generic object that can walk down a possibly-wildcard-equipped path.

    Example: given a path `one.two.three` and a root with subtree `*.three`,
    `NodeFinder(root).step(one).step(two).step(three)` will return the node
    at `*.three` (assuming that nothing more specific hangs off `the root`).

    If nothing is found, raises `KeyError`.
    """

    def __init__(self, src):
        self.steps = ((src, False),)

    def step(self, name, new=False):
        steps = []
        for node, keep in self.steps:
            if name in node:
                steps.append((node.get(name), False))
        for node, keep in self.steps:
            if "+" in node:
                steps.append((node.get("+"), False))
        for node, keep in self.steps:
            if "#" in node:
                steps.append((node.get("#"), True))
        for node, keep in self.steps:
            if keep:
                steps.append((node, True))
            # Nodes found with '*' stay on the list
            # so that they can match multiple path elements.
        if not steps:
            raise KeyError(name)
        self.steps = steps

    @property
    def result(self) -> tuple[Path,Node]:
        s = self.steps[0]
        return s[0]

