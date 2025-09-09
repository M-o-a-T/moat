"""
Rudimentary Github API.
"""
from __future__ import annotations

from httpx import AsyncClient
from contextlib import asynccontextmanager
from moat.util import to_attrdict

from . import API as BaseAPI
from . import RepoInfo as BaseRepoInfo

class RepoInfo(BaseRepoInfo):
    def __init__(self, json):
        self.data = to_attrdict(json)
        super().__init__(self.data.name)

    @property
    def git(self) -> str:
        return self.data.git_url.replace("git://github.com/","git@github.com:")

    @property
    def parent(self) -> str:
        breakpoint()
        return "parent" in self.data or "source" in self.data

    async def clone_to(self, path:anyio.Path, name:str|None=None):
        return await super().clone_to(self.git,path, name=name)

    

class API(BaseAPI):
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

    async def list_repos(self) -> AsyncIterator[str]:
        """
        List accessible repositories.
        """
        pg=None
        url = f"/users/{self.cfg.user}/repos"
        while url is not None:
            res = await self.http.get(url)
            res.raise_for_status()
            for k in res.json():
                yield k["name"]
            try:
                lh = res.headers["link"]
            except KeyError:
                return
            url = None
            for xh in lh.split(","):
                u,r = xh.split(";")
                if 'rel="next"' in r:
                    url = u.strip().lstrip("<").rstrip(">")
                    break

    async def get_repo(self, name) -> RepoInfo:
        url = f"/repos/{self.cfg.user}/{name}"
        res = await self.http.get(url)
        return RepoInfo(res.json())

