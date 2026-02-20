"""
This module contains the basic MoaT-Link data model.
"""

from __future__ import annotations

from logging import getLogger

from attrs import define, field

from moat.util import (
    NotGiven,
    attrdict,
    combine_dict,
)
from moat.lib.path import (
    Path,
    PathLongener,
    PathShortener,
)
from moat.link.meta import MsgMeta
from moat.util.exc import ExpKeyError

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.lib.rpc import Key

    from collections.abc import Awaitable, Callable, Iterator
    from typing import Any

__all__ = ["Node"]

logger = getLogger(__name__)


def _keys_repr(x):
    return ",".join(str(k) for k in x)


@define
class Node:
    """Represents one MoaT-Link item."""

    _data: Any = field(init=False, default=NotGiven)
    _meta: MsgMeta | None = field(init=False, default=None)

    _sub: dict[Key, Node] = field(init=False, factory=dict, repr=_keys_repr)  # sub-entries

    def set(self, item: Path, data: Any, meta: MsgMeta, force: bool = False) -> bool | None:
        """Save new data below this node.

        Return semantics:
        * if @force is set:
          * `True`: incoming timestamp is newer
          * `None`: incoming data are equal
          * `False`: otherwise
        * if @force is not set:
          * `None`: incoming data are equal
          * `False`: incoming timestamp is older
          * `True`: otherwise
        """
        assert isinstance(meta, MsgMeta)
        s = self.get(item)
        if s._meta is not None:  # noqa:SLF001
            same = s._data == data  # noqa:SLF001
            if force:
                if meta.timestamp > s._meta.timestamp:  # noqa:SLF001
                    s.set_(item, data, meta)
                    return True
                if same:
                    return None
                return False
            if same:
                return None
            if meta.timestamp < s._meta.timestamp:  # noqa:SLF001
                return False
        s.set_(item, data, meta)
        return True

    def set_(self, path: Path, data: Any, meta: MsgMeta):
        "Low-level node data setter. The (sub)path is not stored by default."
        path  # noqa:B018
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

    def keys(self):  # noqa: D102
        return self._sub.keys()

    def items(self):  # noqa: D102
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
            s, p = ps.short(p)  # noqa:PLW2901
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
            it = iter(v._dump(path + (k,), level))  # noqa: SLF001
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
                n._data = d  # noqa: SLF001
                n._meta = m  # noqa: SLF001

    @property
    def meta(self) -> MsgMeta | None:
        "return current metadata"
        return self._meta

    @meta.deleter
    def meta(self) -> None:
        "Clear metadata"
        self._meta = None

    def __delitem__(self, item) -> None:
        """
        Remove an item. (It must be empty.)

        **Warning** Don't call this unless the timeout for deletion has passed.
        """
        d = self._sub[item]

        if d._sub or d.data_ is not NotGiven:  # noqa: SLF001
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
                    raise ExpKeyError(k) from None
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
                    s = s.add_child(k)
                else:
                    if create is True and n == len(item) - 1 and s._data is not NotGiven:  # noqa: SLF001
                        raise KeyError(k)
            return s

        try:
            res = self._sub[item]
        except KeyError:
            if create is False:
                raise
            return self.add_child(item)
        else:
            if create is True and res._data is not NotGiven:  # noqa: SLF001
                raise KeyError(item)
            return res

    def add_child(self, item):
        """Create and register a new child node.

        Override this method to return a different node type for
        specific child names.

        Args:
            item: the key for the new child.

        Returns:
            The newly-created child node.

        Raises:
            ValueError: if *item* already exists.
        """
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
        proc: Callable[[Path, Node], Awaitable[bool | None]],
        max_depth: int = 999999,
        min_depth: int = 0,
        timestamp: float = 0,
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
            if depth_first and (max_depth is None or max_depth > len(p)):
                for k, v in s._sub.items():  # noqa: SLF001
                    await _walk(v, p / k)

            if (min_depth is None or min_depth <= len(p)) and (
                force or (s.meta is not None and s.meta.timestamp >= timestamp)
            ):
                if await proc(p, s) is False:
                    return

            if not depth_first and (max_depth is None or max_depth > len(p)):
                for k, v in list(s._sub.items()):  # noqa: SLF001
                    await _walk(v, p / k)

        await _walk(self, Path())

    def search(self, path: Path) -> Node:
        """
        Find the destination node of a path, including wildcards.

        This node represents the pattern.
        """
        nf = NodeFinder(self)
        for elem in path:
            nf.step(elem)
        return nf.result

    def collect(self, path: Path, keep: bool = False) -> dict:
        """
        Collate data from all matching branches for a path.

        This method combines all data nodes found in the matching
        ``NodeFinder`` branches, with more specific matches overriding
        less specific ones.
        """
        nf = NodeFinder(self)
        for p in path:
            try:
                nf.step(p)
            except KeyError:
                break

        res: dict = attrdict()
        for node in reversed(nf.matches):
            if node.data_ is not NotGiven:
                res = combine_dict(node.data_, res, cls=attrdict, keep=keep)

        return res


class NodeFinder:
    """A generic object that can walk down a possibly-wildcard-equipped path.

    Example: given a path ``one.two.three`` and a root with subtree ``*.three``,
    ``NodeFinder(root).step(one).step(two).step(three).result`` will return
    the node at ``*.three`` (assuming that nothing more specific hangs off
    the root).

    If nothing is found, raises `KeyError`.
    """

    def __init__(self, src):
        self.steps = ((src, 0, 0),)

    @staticmethod
    def _range_wildcards(node):
        """Yield `(min,max,node)` tuples for valid range wildcard children."""

        for key, sub in node._sub.items():  # noqa:SLF001
            if not isinstance(key, tuple) or len(key) != 2:
                continue
            n, m = key
            if type(n) is not int or type(m) is not int:
                continue
            if n < 1:
                continue
            if m != 0 and m < n:
                continue
            yield n, m, sub

    def step(self, name: str | int | bool | None, new=False):
        """
        Walk a single hierarchy step, observing wildcards. Note that ``#``
        means *one or more*, i.e. it will not match an empty path element.

        Args:
            name: the path element to look at.

        Don't use the *new* argument; it only exists for override compatibility.
        """
        if new:
            raise ValueError("I can't create new nodes.")

        steps = []
        for node, min_more, max_more in self.steps:
            if min_more == 0:
                if name in node:
                    steps.append((node.get(name), 0, 0))
                if "+" in node:
                    steps.append((node.get("+"), 0, 0))
                for n, m, sub in self._range_wildcards(node):
                    steps.append((sub, n - 1, None if m == 0 else m - 1))
                if "#" in node:
                    steps.append((node.get("#"), 0, None))

            if max_more is None or max_more > 0:
                steps.append((
                    node,
                    max(min_more - 1, 0),
                    None if max_more is None else max_more - 1,
                ))
            # Nodes found with '#' or range wildcards stay on the list
            # so that they can match additional path elements.
        if not steps:
            raise KeyError(name)
        self.steps = steps

    @property
    def result(self) -> Node:
        for node in self.matches:
            return node
        raise KeyError("No matching wildcard state")

    @property
    def matches(self) -> tuple[Node, ...]:
        """Return all applicable branch nodes in precedence order."""

        seen: set[int] = set()
        res: list[Node] = []
        for node, min_more, _max_more in self.steps:
            if min_more != 0:
                continue
            node_id = id(node)
            if node_id in seen:
                continue
            seen.add(node_id)
            res.append(node)
        return tuple(res)
