"""
Non-embedded helpers, mainly for the command interpreter
"""

from __future__ import annotations

import hashlib

from ._util import TEST_MAGIC as TEST_MAGIC
from ._util import Repeater as Repeater
from ._util import Sensor as Sensor
from ._util import del_p as del_p
from ._util import get_p as get_p
from ._util import set_p as set_p
from .files import APath, copytree

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.micro.files import MoatPath

    from collections.abc import Awaitable, Callable
    from typing import Any


__all__ = ["Repeater", "Sensor", "del_p", "get_p", "hash256", "run_update", "set_p"]


def hash256(data: bytes) -> bytes:
    """Hash a chunk of bytes the way git does."""
    h = hashlib.sha256()
    h.update(data)
    return h.digest()


async def _rd(f: APath) -> bytes:
    """Return file contents."""
    async with await f.open("rb") as fd:
        return await fd.read()


async def run_update(*a: Any, **kw: Any) -> None:
    """
    Update a remote file system.

    The satellite contains a list of hashes for its modules.

    Thus if the source of that frozen file is identical to what we have
    now, the remote shouldn't have that file (or its .mpy derivative) in
    its file system. It might however be there as a left-over artefact from
    a previous online update. Thus we delete it.
    """
    import moat.micro._embed.lib as emb  # noqa: PLC0415

    for p in emb.__path__:
        src = APath(p)
        await _run_update(src, *a, **kw)


async def _run_update(
    src: APath,
    dest: MoatPath,
    check: Any = None,
    cross: Any = None,
    arch: str | None = None,
    hash_fn: Callable[[str], Awaitable[bytes | None]] | None = None,
) -> None:
    """Update a single _embed/lib directory."""

    async def drop(dst: APath) -> bool | None:
        """
        Delete files on the satellite that didn't change between the
        version in their firmware and our current version.
        """
        # rp = dst.relative_to(emb_r)
        if dst.name == "manifest.py":
            return None

        # assume dst is relative
        sp = src.parent / dst
        # XXX we might want to ask git which files differ,
        # it's supposed to have a cache for that
        dn = str(dst)[:-3].replace("/", ".").lstrip(".")
        dn = dn.removeprefix("lib.")
        dn = dn.removesuffix(".__init__")
        if hash_fn is None:
            return False
        try:
            res = await hash_fn(dn)
            if res is None:
                return False
        except (ImportError, KeyError):
            return False
        rs = await _rd(sp)
        return res == hash256(rs)[: len(res)]

    await copytree(src, dest, check=check, drop=drop, cross=cross, arch=arch)
