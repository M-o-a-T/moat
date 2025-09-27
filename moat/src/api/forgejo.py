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

#   async def clone_from(self, src_repo):
#       """
#       Tell the destination to clone from this source.
#       """
#       raise NotImplementedError()
#       # disabled because codeforge takes too long for this

#       url = "repos/migrate"
#       scfg = src_repo.api.cfg

#       data = dict(
#           auth_username=scfg.user,
#           service=scfg.api,
#           clone_addr=src_repo.data.git_url,

#           repo_name=src_repo.name,
#           repo_owner=self.cfg.user,
#           description=src_repo.description,

#           issues=True,
#           private=False,
#           releases=True,
#       )
#       if "token" in scfg:
#           data["auth_token"] = scfg.token

#       try:
#           res = await self.http.post(url, data=data, timeout=99)
#           res.raise_for_status()
#       except Exception:
#           breakpoint()

#       return await self.get_repo(src_repo.name)

#   async def add_repo(self, name:str, description: str):
#       """
#       Add this repository.
#       """
#       url = "/user/repos"
#       data = dict(
#           name=name,
#           description=description,
#           private=False,
#           default_branch="main",
#           auto_init=False,
#           object_format_name="sha1",
#       )
#       res = await self.http.post(url, data=data)
#       return RepoInfo(self, res.json())

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

#   async def get_repo(self, name) -> RepoInfo:
#       pass
