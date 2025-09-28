"""
Rudimentary Github API.
"""

from __future__ import annotations

from httpx import AsyncClient
from contextlib import asynccontextmanager
from subprocess import CalledProcessError

from moat.util import attrdict

from ._common import API as BaseAPI
from ._common import CommitInfo as BaseCommitInfo
from ._common import RepoInfo as BaseRepoInfo
from . import NoSuchRepo


class CommitInfo(BaseCommitInfo):
    pass


class RepoInfo(BaseRepoInfo):
    @property
    def name(self):
        return self.repo.name

    @property
    def ssh_url(self) -> str:
        try:
            return self.api.cfg.ssh_url
        except AttributeError:
            return f"git+ssh://{self.api.cfg.get('git_user', 'git')}@{self.api.host}/{self.api.cfg.get('repo', self.name + '.git')}"

    @property
    def git_url(self) -> str:
        try:
            return self.api.cfg.git_url
        except AttributeError:
            return f"https://{self.api.host}/{self.cfg.get('repo', self.name + '.git')}"

    @property
    def ext_url(self) -> str:
        try:
            return self.api.cfg.ext_url
        except AttributeError:
            return f"https://{self.api.host}/{self.api.cfg.get('repo', self.name)}"

    async def load_(self) -> RepoInfo:
        try:
            async with self.repo.git_lock:
                await self.repo.exec("git", "remote", "get-url", self.api.name, capture=True)
        except CalledProcessError:
            raise NoSuchRepo(self)

        self.data = attrdict()

    async def create(self):
        """
        Create this repository.
        """
        await self.repo.exec(self.api.cfg.command, self.name)

    async def set_remote(self):
        """
        Override: the config program is responsible for push setup
        """
        pass


class API(BaseAPI):
    cls_RepoInfo = RepoInfo
    cls_CommitInfo = CommitInfo

    async def clone_from_remote(self):
        """
        Clone this repository to the local cache.
        """
        raise NotImplementedError()

    async def add_repo(self, name: str, description: str):
        """
        Add this repository.
        """
        raise NotImplementedError()

    #   async def list_repos(self) -> AsyncIterator[str]:
    #       """
    #       List accessible repositories.
    #       """
    #       url = f"/users/{self.cfg.user}/repos"
    #       while url is not None:
    #           res = await self.http.get(url)
    #           res.raise_for_status()
    #           for k in res.json():
    #               yield k
    #           try:
    #               lh = res.headers["link"]
    #           except KeyError:
    #               return
    #           url = None
    #           for xh in lh.split(","):
    #               u,r = xh.split(";")
    #               if 'rel="next"' in r:
    #                   url = u.strip().lstrip("<").rstrip(">")
    #                   break

    async def get_repo(self, name) -> RepoInfo:
        return self.cls_RepoInfo(self, name)
