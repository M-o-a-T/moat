"""
Common code for repository APIs.

This is somewhat ad-hoc.
"""

from __future__ import annotations

from abc import ABCMeta, abstractmethod
from contextlib import asynccontextmanager
from attr import define,field
from moat.util import CtxObj, ungroup
import logging
import anyio


class API(CtxObj, metaclass=ABCMeta):
    "Base class for forge APIs"

    _tg: anyio.abc.TaskGroup
    _njobs: int = 0
    _ended: anyio.Event | None = None

    def __init__(self, cfg: attrdict):
        self.cfg = cfg
        self.url = cfg["url"]
        self.logger = logging.getLogger(f"moat.src.api.{cfg.api}")

    @asynccontextmanager
    async def _ctx(self) -> AsyncIterator[Self]:
        async with anyio.create_task_group() as self._tg:
            yield self

    async def list_repos(self) -> AsyncIterator[str]:
        """
        List accessible repositories.
        """
        # only required for source repo
        raise NotImplementedError

    @abstractmethod
    async def get_repo(self, name:str) -> RepoInfo:
        """
        Fetch data about this repository.
        """

    async def add_repo(self, name:str):
        """
        Add this repository.
        """
        # only required for destination repo
        raise NotImplementedError


def get_api(cfg: dict, **kw) -> Backend:
    """
    Fetch the API named in the config and initialize it.
    """
    from importlib import import_module

    name = cfg["api"]
    if "." not in name:
        name = "moat.src.api." + name
    return import_module(name).API(cfg, **kw)


@define
class RepoInfo(metaclass=ABCMeta):
    api = field(type=API)
    name = field(type=str)

    @property
    @abstractmethod
    def git(self) -> str:
        """git URL"""

    @property
    @abstractmethod
    def parent(self) -> str:
        """parent repo URL"""

    async def clone_to(self, url:str, path:anyio.Path, name:str|None=None):
        """
        Clone this repository locally.
        """
        orig = () if name is None else ("--origin", name)
        await anyio.run_process(["git","clone",*orig, url, str(path)])
         # , *, input=None, stdin=None, stdout=-1, stderr=-1, check=True, cwd=None, env=None,  + startupinfo=None, creationflags=0, start_new_session=False, pass_fds=(), user=None,          + group=None, extra_groups=None, umask=-1)

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

    async def drop_branch(self, tag:str) -> None:
        """
        Delete this tag.
        """
        # only required for source repo
        raise NotImplementedError

    async def drop_tag(self, tag:str) -> None:
        """
        Delete this tag.
        """
        # only required for source repo
        raise NotImplementedError

    async def get_branch(name) -> CommitInfo:
        """
        Return info on this branch.
        """
        raise NotImplementedError

    async def get_tag(name) -> CommitInfo:
        """
        Return info on this tag.
        """
        raise NotImplementedError


@define
class CommitInfo(metaclass=ABCMeta):
    repo = field(type=RepoInfo)
    name = field(type=str)
    hash = field(type=str)


