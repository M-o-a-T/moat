"""
Rudimentary Github API.
"""
from __future__ import annotations

from httpx import AsyncClient
from contextlib import asynccontextmanager

from ._common import API as BaseAPI
from ._common import CommitInfo as BaseCommitInfo
from ._common import RepoInfo as BaseRepoInfo

class CommitInfo(BaseCommitInfo):
    pass

class RepoInfo(BaseRepoInfo):
    @property                                                                                  
    def git(self) -> str:                                                                      
        return self.data.git_url.replace("git://github.com/","git@github.com:")

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
            hdr["Authorization"] = "token "+self.cfg["token"]
        async with (
            AsyncClient(base_url=self.api_url+"/api/v1/", headers=hdr) as self.http,
            super()._ctx(),
        ):
            yield self

