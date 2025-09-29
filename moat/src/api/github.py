"""
Rudimentary Github API.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from attr import define, field
from httpx import AsyncClient

from moat.util import to_attrdict

from ._common import API as BaseAPI
from ._common import CommitInfo as BaseCommitInfo
from ._common import RepoInfo as BaseRepoInfo

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from typing import Self


@define
class CommitInfo(BaseCommitInfo):  # noqa: D101
    data = field(init=False)

    def __init__(self, repo, json):
        self.data = to_attrdict(json)
        super().__init__(repo, self.data.commit.sha)


class RepoInfo(BaseRepoInfo):  # noqa: D101
    cls_CommitInfo = CommitInfo

    @property
    def parent(self) -> dict | None:
        "Return info about the parent repo, or None"
        if (par := self.data.get("parent", None)) is not None:
            return par
        if (par := self.data.get("source", None)) is not None:
            return par
        return None


class API(BaseAPI):  # noqa: D101
    cls_RepoInfo = RepoInfo
    cls_CommitInfo = CommitInfo

    @asynccontextmanager
    async def _ctx(self) -> AsyncIterator[Self]:
        hdr = {
            "X-GitHub-Api-Version": "2022-11-28",
            "Accept": "application/vnd.github+json",
        }
        if "token" in self.cfg:
            hdr["Authorization"] = "Bearer " + self.cfg["token"]
        async with (
            AsyncClient(base_url="https://api.github.com", headers=hdr) as self.http,
            super()._ctx(),
        ):
            yield self

    @property
    def host(self):
        "Host to talk to"
        return self.cfg.get("host", "github.com")
