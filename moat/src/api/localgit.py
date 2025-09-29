"""
Rudimentary Github API.
"""

from __future__ import annotations

from subprocess import CalledProcessError

from moat.util import attrdict

from . import NoSuchRepo
from ._common import API as BaseAPI
from ._common import CommitInfo as BaseCommitInfo
from ._common import RepoInfo as BaseRepoInfo


class CommitInfo(BaseCommitInfo):  # noqa: D101
    pass


class RepoInfo(BaseRepoInfo):  # noqa: D101
    @property
    def name(self):  # noqa: D102
        return self.repo.name

    @property
    def ssh_url(self) -> str:  # noqa: D102
        try:
            return self.api.cfg.ssh_url
        except AttributeError:
            return (
                f"git+ssh://{self.api.cfg.get('git_user', 'git')}@"
                f"{self.api.host}/{self.api.cfg.get('repo', self.name + '.git')}"
            )

    @property
    def git_url(self) -> str:  # noqa: D102
        try:
            return self.api.cfg.git_url
        except AttributeError:
            return f"https://{self.api.host}/{self.cfg.get('repo', self.name + '.git')}"

    @property
    def ext_url(self) -> str:  # noqa: D102
        try:
            return self.api.cfg.ext_url
        except AttributeError:
            return f"https://{self.api.host}/{self.api.cfg.get('repo', self.name)}"

    async def load_(self) -> RepoInfo:  # noqa: D102
        try:
            async with self.repo.git_lock:
                await self.repo.exec("git", "remote", "get-url", self.api.name, capture=True)
        except CalledProcessError as exc:
            raise NoSuchRepo(self) from exc

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


class API(BaseAPI):  # noqa: D101
    cls_RepoInfo = RepoInfo
    cls_CommitInfo = CommitInfo

    async def clone_from_remote(self):
        """
        Clone this repository to the local cache.
        """
        raise NotImplementedError

    async def add_repo(self, name: str, description: str):
        """
        Add this repository.
        """
        raise NotImplementedError

    # async def list_repos(self) -> AsyncIterator[str]:
    #   """
    #   List accessible repositories.
    #   """
    #   url = f"/users/{self.cfg.user}/repos"
    #   while url is not None:
    #       res = await self.http.get(url)
    #       res.raise_for_status()
    #       for k in res.json():
    #           yield k
    #       try:
    #           lh = res.headers["link"]
    #       except KeyError:
    #           return
    #       url = None
    #       for xh in lh.split(","):
    #           u,r = xh.split(";")
    #           if 'rel="next"' in r:
    #               url = u.strip().lstrip("<").rstrip(">")
    #               break

    async def get_repo(self, name) -> RepoInfo:  # noqa: D102
        return self.cls_RepoInfo(self, name)
