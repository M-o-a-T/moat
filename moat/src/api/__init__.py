"""
Common code for repository APIs.

This is somewhat ad-hoc.
"""

from __future__ import annotations

import anyio
import logging
from abc import ABCMeta, abstractmethod
from contextlib import asynccontextmanager

from attr import define, field

from moat.util import CtxObj
from moat.util.exec import run as run_

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.util import attrdict
    from moat.src.move import RepoMover as RepoMover

    from collections.abc import AsyncIterator, Awaitable
    from typing import Self


class NoSuchRepo(RuntimeError):
    "doesn't exist, call create"

    pass


class RepoExists(RuntimeError):
    "exists, cannot create"

    pass


@define
class Repo:  # noqa: D101
    name = field()
    cwd = field(default=None, type=anyio.Path)

    def __attrs_post_init__(self):
        if self.cwd is None:
            self.cwd = anyio.Path(self.cfg.cache) / self.name

    def run(self, *a, **kw) -> Awaitable:
        """Run a program in this repo's directory"""
        kw.setdefault("cwd", self.cwd)
        return run_(*a, **kw)


@define
class RepoInfo(metaclass=ABCMeta):
    """Wrapper for a particular remote repository."""

    api: API = field()
    repo: Repo = field()

    @property
    def description(self) -> str:
        """One-liner"""
        raise NotImplementedError

    @property
    def parent(self) -> str:
        """parent repo URL"""
        raise NotImplementedError

    @property
    def main(self) -> str:
        """name of main branch"""
        raise NotImplementedError

    @abstractmethod
    async def load_(self):
        "load data. Will raise NoSuchRepo if it doesn't exist."
        pass

    @abstractmethod
    async def create(self):
        "create remote repo."
        pass

    async def load(self, create: bool | None = None):
        "load this repo's data. You might want to overide `load_` instead."
        try:
            await self.load_()
        except NoSuchRepo:
            if create is False:
                raise
        else:
            if create:
                raise RepoExists(self.repo)
            return

        await self.create()
        await self.load_()

    async def get_branches(self) -> AsyncIterator[str]:
        """
        List known (local) branches.
        """
        # only required for source repo
        raise NotImplementedError

    async def get_tags(self) -> AsyncIterator[str]:
        """
        List known tags.
        """
        # only required for source repo
        raise NotImplementedError

    async def get_branch(self, name) -> CommitInfo:
        """
        Return info on this branch.
        """
        raise NotImplementedError

    async def get_default_branch(self) -> str:
        """
        Get the name of the default branch.
        """
        raise NotImplementedError

    async def set_default_branch(self, name):
        """
        Set the default branch to this.
        """
        raise NotImplementedError

    async def get_tag(self, name) -> CommitInfo:
        """
        Return info on this tag.
        """
        raise NotImplementedError

    async def push(self) -> CommitInfo:
        """
        git-push to this repo.
        """
        await self.repo.exec("git", "push", self.api.name)

    async def pull(self) -> CommitInfo:
        """
        git-pull from this repo.
        """
        await self.repo.exec("git", "fetch", self.api.name)

    async def drop_tags(self, *names: str) -> None:
        """
        Delete tags.
        """
        if not names:
            return
        await self.repo.exec("git", "push", self.api.name, *(f":{n}" for n in names))

    async def drop_branches(self, *names: str) -> None:
        """
        Delete branches.
        """
        if not names:
            return
        await self.repo.exec("git", "push", self.api.name, *(f":{n}" for n in names))


@define
class CommitInfo(metaclass=ABCMeta):  # noqa: D101,B024
    repo = field(type=RepoInfo)
    hash = field(type=str)


class API(CtxObj, metaclass=ABCMeta):
    "Base class for forge APIs"

    cls_RepoInfo = RepoInfo
    cls_CommitInfo = CommitInfo

    _tg: anyio.abc.TaskGroup
    _njobs: int = 0
    _ended: anyio.Event | None = None

    def __init__(self, name: str, cfg: attrdict):
        self.name = name
        self.cfg = cfg
        self.logger = logging.getLogger(f"moat.src.api.{name}")

    def __repr__(self):
        return f"‹{self.cfg.api}›"

    @asynccontextmanager
    async def _ctx(self) -> AsyncIterator[Self]:
        async with anyio.create_task_group() as self._tg:
            yield self

    @property
    def host(self):
        "Host to talk to"
        raise NotImplementedError

    async def list_repos(self) -> AsyncIterator[str]:
        """
        List accessible repositories.
        """
        # only required for source repo
        raise NotImplementedError

    def repo_info_for(self, repo: Repo) -> RepoInfo:
        """
        Fetch info data for this repository.

        Will fail when the destination doesn't exist.
        """
        return self.cls_RepoInfo(self, repo)


def get_api(cfg: dict, name: str) -> API:
    """
    Return the API from the config (module ``cfg['api']``).

    The name is the key which the API is found under.
    """
    from importlib import import_module  # noqa: PLC0415

    md = cfg.api
    if "." not in md:
        md = f"moat.src.api.{md}"
    return import_module(md).API(name, cfg)
