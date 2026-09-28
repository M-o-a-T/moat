"""
Test roots for code-snippet tests.

Every test run gets its own subtree, ``:R.test:PID:SEQ``, so that
parallel tests don't collide. Paths in a test case's data, args and
steps are resolved against it before they reach the snippet or the Link
client:

* unrooted paths, and paths starting with ``:T``, are below the test root;
* ``:R`` paths are absolute paths in the tree; they lose the root marker.

The result is an ordinary, unprefixed path, which is what the Link client
expects; the snippet under test needs no test awareness.

The ``T_Root`` context variable is intentionally *not* set to the test
root: incoming MQTT topics would then be tagged with ``:T`` instead of
``:R``, which the Link client does not expect.
"""

from __future__ import annotations

import anyio
import os
from contextlib import asynccontextmanager
from itertools import count

from moat.lib.path import Path, RootPath

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from moat.link.client import LinkSender

    from collections.abc import AsyncIterator

__all__ = ["TEST_ROOT", "TestRoot", "with_test_root"]

TEST_ROOT = Path.build(("test",))
"The subtree below :R where test roots are allocated."

_seq = count(1)


def _plain(elems: tuple) -> Path:
    "Build an unprefixed path without scanning for roots."
    return Path(*elems, _warn=False)


class TestRoot:
    """
    A test root, and path resolution against it.

    Args:
        path: The test root, relative to ``:R``. Defaults to a new
              ``test.PID.SEQ`` path.
    """

    __test__ = False  # not a pytest class

    path: Path

    def __init__(self, path: Path | None = None):
        if path is None:
            path = _plain(TEST_ROOT.raw + (os.getpid(), next(_seq)))
        elif path.has_prefix or path.is_relative:
            raise ValueError(f"The test root must be a plain path, not {path}")
        self.path = path

    def __repr__(self):
        return f"TestRoot({self.path})"

    def resolve_path(self, path: Path) -> Path:
        """
        Resolve a single path.

        Unrooted and ``:T`` paths get the test root prepended, ``:R``
        paths lose their root marker. Other roots, and relative paths,
        are rejected.
        """
        if path.is_relative:
            raise ValueError(f"Relative paths are not supported here: {path}")
        if not path.has_prefix:
            return _plain(self.path.raw + path.raw)

        root, *rest = path.raw_rooted
        assert isinstance(root, RootPath)
        match root.key:
            case "T":
                return _plain(self.path.raw + tuple(rest))
            case "R":
                return _plain(tuple(rest))
            case _:
                raise ValueError(f"Only :R and :T roots are supported here: {path}")

    def resolve(self, data: Any) -> Any:
        """
        Resolve all paths in @data.

        Mappings, lists and tuples are processed recursively and copied;
        mapping keys are not touched. Anything else is returned unchanged.
        """
        if isinstance(data, Path):
            return self.resolve_path(data)
        if isinstance(data, Mapping):
            return type(data)((k, self.resolve(v)) for k, v in data.items())  # pyright:ignore
        if isinstance(data, (list, tuple)):
            return type(data)(self.resolve(v) for v in data)
        return data

    async def delete(self, link: LinkSender) -> None:
        "Delete the test subtree."
        await link.d.delete(self.path, rec=True)


@asynccontextmanager
async def with_test_root(link: LinkSender, *, keep: bool = False) -> AsyncIterator[TestRoot]:
    """
    Allocate a new test root; delete its subtree afterwards, even if the
    test failed, unless @keep is set.
    """
    tr = TestRoot()
    try:
        yield tr
    finally:
        if not keep:
            with anyio.CancelScope(shield=True), anyio.move_on_after(10):
                await tr.delete(link)
