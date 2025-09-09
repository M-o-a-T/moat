"""
Rudimentary Github API.
"""
from __future__ import annotations

from . import API as BaseAPI
from httpx import AsyncClient
from contextlib import asynccontextmanager

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
            AsyncClient(base_url=self.url, headers=hdr) as self.http,
            super()._ctx(),
        ):
            yield self

    async def list_repos(self) -> AsyncIterator[str]:
        """
        List accessible repositories.
        """
        pg=None
        while True:
            res = await self.http.get(f"/users/{self.cfg.user}/repos")
            from pprint import pprint
            pprint(res)
            # curl --request GET --url "https://api.github.com/users/smurfix/repos" --header "Accept: application/vnd.github+json"  --header "Authorization: Bearer ghp_NO_WAY" --header "X-GitHub-Api-Version: 2022-11-28" ^C


    async def get_repo(self, name) -> RepoInfo:
        pass
