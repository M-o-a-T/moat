"""
Rudimentary Github API.
"""

from __future__ import annotations

from attr import define

from moat.util import to_attrdict

from . import API as BaseAPI
from . import CommitInfo as BaseCommitInfo
from . import NoSuchRepo, RepoExists
from . import RepoInfo as BaseRepoInfo

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from . import Repo

    from collections.abc import AsyncIterator


@define
class CommitInfo(BaseCommitInfo):
    pass


#   data = field(init=False)

#   def __init__(self, repo, json):
#       self.data = to_attrdict(json)
#       super().__init__(repo, self.data.name, self.data.commit.sha)


class RepoInfo(BaseRepoInfo):
    """Remote repository data,"""

    def __init__(self, api: API, repo: Repo):
        self.data = None  # setup
        super().__init__(api, repo)

    @property
    def git_url(self) -> str:
        "URL used to pull with git"
        if "git_url" in self.api.cfg:
            return self.api.cfg.git_url.replace("{{repo}}", self.name)
        return f"https://{self.api.host}/{self.api.org}/{self.repo.name}.git"

    @property
    def ssh_url(self) -> str:
        "URL to write to the repository via git"
        return f"git+ssh://git@{self.api.host}/{self.api.org}/{self.repo.name}.git"

    @property
    def ext_url(self) -> str:
        "URL used to view the thing"
        return f"https://{self.api.host}/{self.api.org}/{self.repo.name}"

    @property
    def description(self) -> str:
        return self.data.description.strip().split("\n", 1)[0]

    async def load_(self) -> RepoInfo:
        url = f"repos/{self.api.org}/{self.repo.name}"
        res = await self.api.http.get(url)
        if res.status_code == 404:
            raise NoSuchRepo(self)
        res.raise_for_status()
        self.data = to_attrdict(res.json())

    async def create(self):
        """
        Create this repository.
        """
        url = "user/repos"
        data = dict(
            name=self.repo.name,
            description=self.repo.description,
            private=False,
            default_branch=self.repo.cfg.branch,
            auto_init=False,
            object_format_name="sha1",
        )
        res = await self.api.http.post(url, json=data)
        if res.status_code == 409:
            raise RepoExists(self)
        res.raise_for_status()
        await self.set_remote()

    async def set_remote(self):
        """
        Set this remote's URL, and configure pushing
        """
        async with self.repo.git_lock:
            await self.repo.exec("git", "remote", "add", self.api.name, self.ssh_url)
            await self.repo.exec(
                "git", "config", "set", "--append", f"remote.{self.api.name}.push", "refs/heads/*"
            )

    @property
    def parent(self) -> dict | None:
        "Return info about the parent repo, or None"
        if (par := self.data.get("parent", None)) is not None:
            return par
        return None

    @property
    def main(self) -> str:
        """name of main branch"""
        return self.data["default_branch"]

    async def clone_from_remote(self):
        """
        Clone this repository to the local cache.
        """
        if await self.repo.cwd.exists():
            async with self.repo.git_lock:
                await self.repo.exec("git", "remote", "update")
        else:
            await self.repo.exec(
                "git",
                "clone",
                "--bare",
                "--origin",
                self.api.name,
                self.ssh_url,
                str(self.repo.cwd),
                cwd="/tmp",  # noqa:S108
            )

            async for br in self.get_branches():
                brn = br.data.name
                await self.repo.exec("git", "branch", "--no-track", brn, f"src/{brn}")

        desc = self.repo.cwd / "description"
        if self.description != await desc.read_text():
            await desc.write_text(self.description)
        if not self.repo.cfg.work.kill:
            await self.set_remote()

    async def get_default_branch(self) -> str:
        """
        Get the name of the default branch.
        """
        return self.data.default_branch

    async def set_default_branch(self, name) -> None:
        """
        Set the default branch to this.
        """
        url = f"repos/{self.api.org}/{self.repo.name}"
        res = await self.api.http.patch(url, json=dict(default_branch=name))
        res.raise_for_status()

    async def get_branch(self, name) -> CommitInfo:
        """
        Return info on this branch.
        """
        url = f"repos/{self.api.org}/{self.repo.name}/branches/{name}"
        res = await self.api.http.get(url)
        res.raise_for_status()
        return self.cls_CommitInfo(self, res.json())

    async def get_branches(self) -> AsyncIterator[str]:
        """
        List known branches.
        """
        url = f"repos/{self.api.org}/{self.repo.name}/branches"
        res = await self.api.http.get(url)
        res.raise_for_status()
        for r in res.json():
            yield self.cls_CommitInfo(self, r)

    async def get_tags(self) -> AsyncIterator[str]:
        """
        List known tags.
        """
        url = f"repos/{self.api.org}/{self.repo.name}/tags"
        res = await self.api.http.get(url)
        res.raise_for_status()
        for r in res.json():
            yield r


class API(BaseAPI):
    cls_RepoInfo = RepoInfo
    cls_CommitInfo = CommitInfo

    @property
    def api_url(self) -> str:
        "URL used to view the thing"
        return f"https://{self.cfg.get('api_host', self.cfg.host)}"

    @property
    def host(self):
        "Host to talk to"
        return self.cfg.host

    @property
    def org(self):
        "user/organization to use"
        return self.cfg.get("org", self.cfg.user)

    async def list_repos(self) -> AsyncIterator[str]:
        """
        List accessible repositories.
        """
        url = f"users/{self.cfg.user}/repos"
        while url is not None:
            res = await self.http.get(url)
            res.raise_for_status()
            for k in res.json():
                yield self.cls_RepoInfo(self, k)
            try:
                lh = res.headers["link"]
            except KeyError:
                return
            url = None
            for xh in lh.split(","):
                u, r = xh.split(";")
                if 'rel="next"' in r:
                    url = u.strip().lstrip("<").rstrip(">")
                    break
