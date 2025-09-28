"""
Non-embedded helpers, mainly for the command interpreter
"""

from __future__ import annotations

import hashlib

from .path import APath, copytree

# Typing

from typing import TYPE_CHECKING  # isort:skip

if TYPE_CHECKING:
    from moat.micro.path import MoatPath


def hash256(data):
    "Hash a chunk of bytes the way git does"
    h = hashlib.sha256()
    h.update(data)
    return h.digest()


async def _rd(f):
    "return file contents"
    async with await f.open("rb") as fd:
        return await fd.read()


async def run_update(*a, **kw):
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


async def _run_update(src, dest: MoatPath, check=None, cross=None, hash_fn=None):
    # update a single _embed/lib directory

    async def drop(dst):
        """
        delete files on the satellite that didn't change between the
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
        try:
            res = await hash_fn(dn)
            if res is None:
                return False
        except (ImportError, KeyError):
            return False
        rs = await _rd(sp)
        return res == hash256(rs)[: len(res)]

    await copytree(src, dest, check=check, drop=drop, cross=cross)
