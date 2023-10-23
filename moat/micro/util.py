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


def githash(data):
    h = hashlib.sha1()
    h.update(f"blob {len(data)}\0".encode("utf-8"))
    h.update(data)
    return h.digest()


async def rd(f):
    async with await f.open("rb") as fd:
        return await fd.read()


async def run_update(dest: MoatPath, release: str | None = None, check=None, cross=None):
    """
    Update a remote file system.

    The satellite knows which git version its frozen library is built for.
    Thus if the source of that frozen file is identical to what we have
    now, the remote shouldn't have that file (or its .mpy derivative) in
    its file system. It might be there as a left-over artefact from a
    previous update. Thus we delete it.
    """
    import git

    src = APath(__file__).parent / "_embed"
    root = APath(__file__).parent.parent.parent

    try:
        r = git.Repo(str(root))
    except git.exc.InvalidGitRepositoryError:
        if release:
            raise RuntimeError("release version found but no git")

        async def drop(dst):
            return False

    else:
        if not release:
            # raise RuntimeError("git but no release version found")
            pass
        root_r = await root.resolve()
        emb_r = await src.resolve()
        if release:
            t = r.commit(release).tree
        else:
            t = r.head.commit.tree
        t = t[str(emb_r.relative_to(root_r))]

        async def drop(dst):
            """
            delete files on the satellite that didn't change between the
            version in their firmware and our current version.
            """
            # rp = dst.relative_to(emb_r)
            # assume dst is relative
            sp = src / dst
            # XXX we might want to ask git which files differ,
            # it's supposed to have a cache for that
            if await sp.is_symlink():
                return None  # ignore completely
            try:
                return t[str(dst)].binsha == githash(await rd(sp))
            except KeyError:
                # not yet in git
                return False

        # otherwise sync as normal

    await copytree(src, dest, check=check, drop=drop, cross=cross)
