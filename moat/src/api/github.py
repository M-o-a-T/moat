"""
Rudimentary Github API.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from attr import define,field
from httpx import AsyncClient

from moat.util import to_attrdict

from ._common import API as BaseAPI
from ._common import RepoInfo as BaseRepoInfo
from ._common import CommitInfo as BaseCommitInfo


@define
class CommitInfo(BaseCommitInfo):
    data = field(init=False)

    def __init__(self, repo, json):
        self.data = to_attrdict(json)
        super().__init__(repo, self.data.commit.sha)

class RepoInfo(BaseRepoInfo):
    cls_CommitInfo = CommitInfo

#   @property
#   def git(self) -> str:
#       return self.data.git_url.replace("git://github.com/","git@github.com:")

    @property
    def parent(self) -> dict|None:
        "Return info about the parent repo, or None"
        if (par := self.data.get("parent", None)) is not None:
            return par
        if (par := self.data.get("source", None)) is not None:
            return par
        return None

class API(BaseAPI):
    cls_RepoInfo = RepoInfo
    cls_CommitInfo = CommitInfo

    @asynccontextmanager
    async def _ctx(self) -> AsyncIterator[Self]:
        hdr = {
            "X-GitHub-Api-Version": "2022-11-28",
            "Accept": "application/vnd.github+json",
        }
        if "token" in self.cfg:
            hdr["Authorization"] = "Bearer "+self.cfg["token"]
        async with (
            AsyncClient(base_url="https://api.github.com", headers=hdr) as self.http,
            super()._ctx(),
        ):
            yield self

    @property
    def host(self):
        "Host to talk to"
        return self.cfg.get("host","github.com")

#   async def list_repos(self) -> AsyncIterator[str]:
#       """
#       List accessible repositories.
#       """
#       pg=None
#       url = f"/users/{self.cfg.user}/repos"
#       while url is not None:
#           res = await self.http.get(url)
#           res.raise_for_status()
#           for k in res.json():
#               yield k["name"]
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

#   async def get_repo(self, name) -> RepoInfo:
#       url = f"/repos/{self.cfg.user}/{name}"
#       res = await self.http.get(url)
#       return RepoInfo(self, res.json())

