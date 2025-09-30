"""
Rudimentary Github API.
"""

from __future__ import annotations

import anyio
import os
from subprocess import CalledProcessError

from attr import define

from moat.util import to_attrdict

from . import API as BaseAPI
from . import CommitInfo as BaseCommitInfo
from . import NoSuchRepo
from . import RepoInfo as BaseRepoInfo

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@define
class CommitInfo(BaseCommitInfo):  # noqa: D101
    pass


#   data = field(init=False)

#   def __init__(self, repo, json):
#       self.data = to_attrdict(json)
#       super().__init__(repo, self.data.name, self.data.commit.sha)


@define
class RepoInfo(BaseRepoInfo):  # noqa: D101
    rid: str | None = None
    data: dict | None = None

    @property
    def git_url(self) -> str:
        "URL used to pull with git"
        return f"https://{self.api.cfg.gateway}/{self.rid}.git"

    @property
    def rad_urn(self) -> str:
        "URN to access to the repository"
        return f"rad:{self.rid}"

    @property
    def ext_url(self) -> str:
        "URL used to view the thing"
        return f"https://{self.api.cfg.web}/nodes/{self.api.cfg.gateway}/{self.rid}"

    @property
    def description(self) -> str:
        "Repo description."
        return self.data.payload["xyz.radicle.project"].description

    @property
    def name(self) -> str:  # noqa: D102
        return self.data.payload["xyz.radicle.project"].name

    async def clone_from_remote(self):
        "Copy a remote repo."
        await self.repo.exec("rad", "clone", self.rad_urn, str(self.repo.cwd), cwd="/tmp")  # noqa:S108
        await self.load_()

    async def load_(self):  # noqa: D102
        try:
            self.rid = (await self.repo.exec("rad", ".", capture=True)).strip()
        except CalledProcessError as exc:
            raise NoSuchRepo(self) from exc
        async with (
            anyio.NamedTemporaryFile(mode="w", delete=False) as f,
            anyio.NamedTemporaryFile(mode="r") as g,
        ):
            try:
                await f.write(
                    f"""\
#!/bin/sh
exec cat <$1 >{g.name!r}
"""
                )
                await f.aclose()
                await anyio.Path(f.name).chmod(0o555)
                await self.repo.exec(
                    "rad",
                    "id",
                    "update",
                    "--edit",
                    env={"EDITOR": f.name, "HOME": os.environ["HOME"]},
                )
                import json  # noqa: PLC0415

                self.data = to_attrdict(json.loads(await g.read()))
            finally:
                with anyio.CancelScope(shield=True):
                    await anyio.Path(f.name).unlink()

    async def get_default_branch(self):
        "Get the default branch."
        return self.data.payload["xyz.radicle.project"].defaultBranch

    async def set_default_branch(self, name):
        """
        Set the default branch to this.
        """
        async with anyio.NamedTemporaryFile(delete=False) as f:
            try:
                await f.write_text(
                    f"""\
#!/bin/sh
T=$(mktemp)
jq <$1 >$T f'setpath(["payload","xyz.radicle.project","defaultBranch"];{name!r})'
mv $T $1
"""
                )
                await f.aclose()
                await anyio.Path(f.name).chmod(0o555)
                await self.repo.exec(
                    "rad",
                    "id",
                    "update",
                    "--edit",
                    env={"EDITOR": f.name, "HOME": os.environ["HOME"]},
                )
            finally:
                with anyio.CancelScope(shield=True):
                    await anyio.Path(f.name).unlink()
        self.data.payload["xyz.radicle.project"].defaultBranch = name

    async def create(self):  # noqa: D102
        await self.repo.exec(
            "rad",
            "init",
            "--name",
            self.repo.name,
            "--description",
            self.repo.description,
            "--default-branch",
            self.repo.cfg.branch,
            "--private" if self.api.cfg.private else "--public",
            *(() if self.api.cfg.seed else ("--no-seed",)),
        )


#   async def get_branch(self, name) -> CommitInfo:
#       """
#       Return info on this branch.
#       """
#       url = f"/repos/{self.api.cfg.user}/{self.name}/branches/{name}"
#       res = await self.api.http.get(url)
#       res.raise_for_status()
#       return CommitInfo(self, res.json())
#
#   async def get_branches(self) -> AsyncIterator[str]:
#       """
#       List known branches.
#       """
#       url = f"/repos/{self.api.cfg.user}/{self.name}/branches"
#       res = await self.api.http.get(url)
#       res.raise_for_status()
#       for r in res.json():
#           yield res
#

#   async def get_tags(self) -> AsyncIterator[str]:
#       """
#       List known tags.
#       """
#       url = f"/repos/{self.api.cfg.user}/{self.name}/tags"
#       res = await self.api.http.get(url)
#       res.raise_for_status()
#       breakpoint()
#       for r in res.json():
#           yield res


class API(BaseAPI):  # noqa: D101
    cls_RepoInfo = RepoInfo
    cls_CommitInfo = CommitInfo

    async def list_repos(self) -> AsyncIterator[str]:
        """
        List accessible repositories.
        """
        url = f"/users/{self.cfg.user}/repos"
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

    async def get_repo(self, name) -> RepoInfo:  # noqa: D102
        url = f"/repos/{self.cfg.user}/{name}"
        res = await self.http.get(url)
        res.raise_for_status()
        return self.cls_RepoInfo(self, res.json())
