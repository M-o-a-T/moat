"""
Code that migrates stuff from A to B.
"""

from __future__ import annotations

import anyio
import logging
import subprocess
from contextlib import AsyncExitStack, asynccontextmanager

import jinja2

from moat.util import attrdict
from moat.util.exec import run as run_proc

from .api import API, RepoInfo, get_api

logger = logging.getLogger(__name__)

ProcErr = subprocess.CalledProcessError


class RepoMover:
    """Encapsulate moving a single repository."""

    cf: dict

    def __init__(self, cfg, name):
        self.cfg = cfg
        self.name = name

        self.cwd = loc = anyio.Path(cfg.cache) / name
        self.cwd_ = str(loc)

        self.repos = attrdict()
        self._je = jinja2.Environment(autoescape=False)
        self.git_lock = anyio.Lock()

    @property
    def description(self):  # noqa: D102
        return self.repos.src.description

    async def exec(self, *a, **kw):
        """Helper to run an external program"""

        if "cwd" not in kw:
            kw["cwd"] = self.cwd_

        if "echo" not in kw:
            kw["echo"] = True
            kw["echo_input"] = True

        return await run_proc(*a, **kw)

    async def setup(self):
        """Copy from src to local, set up generic stuff."""
        src = self.repos.src

        if not await self.cwd.exists():
            logger.debug("Cloning %s", self.name)
            try:
                await src.clone_from_remote()
                try:
                    await self.exec("git", "rev-parse", "--verify", src.api.cfg.branch)
                except ProcErr:
                    pass
                else:
                    raise RuntimeError(
                        f"{self.name}: The migration branch "
                        f"{self.cfg.src.branch!r} already exists."
                    )

            except BaseException:
                # XXX do this in Python instead?
                with anyio.CancelScope(shield=True):
                    await self.exec("/bin/rm", "-rf", "--", str(self.cwd), cwd=".")
                raise

        if (
            not await (self.cwd / ".git" / "objects").exists()
            and not await (self.cwd / "objects").exists()
        ):
            # repository may be bare … or not
            raise RuntimeError(f"Incomplete clone of {self.name}")

        cf = attrdict(**self.cfg)
        cf.repos = self.repos  # for templating
        cf.name = self.name
        self.cf = cf

        def render(template, vars=cf):  # noqa: A002
            return self._je.from_string(template).render(vars)

        # Move the master-or-whatever branch to "main"
        defbr = await src.get_default_branch()
        if self.cfg.work.migrate and defbr == self.cfg.src.branch:
            # already gone. Do nothing.
            pass
        elif self.cfg.work.main and defbr != "main":
            logger.debug(f"{self.name} : Renaming the {defbr} branch to 'main'")
            await self.exec("git", "branch", "-m", defbr, "main")
            await self.exec("git", "push", "src", "main")
            if not self.cfg.work.moved:
                await src.set_default_branch("main")
            await self.exec("git", "push", "src", f":{defbr}")

    async def move(self, dst: RepoInfo):
        """Copy our repo to B."""

        await dst.load()  # creates it if it doesn't exist
        await dst.push()

    async def finish(self):
        """Finalize the move"""
        cfg = self.cfg
        src_repo = self.repos.src

        def render(template, vars=self.cf):  # noqa: A002
            return self._je.from_string(template).render(vars)

        if cfg.work.migrate:
            # Add a standalone 'moved-away' branch with a short README.
            try:
                await self.exec("git", "rev-parse", "--verify", cfg.src.branch)
            except ProcErr:
                logger.debug("Creating exit branch %r", cfg.src.branch)

                r = render(cfg.readme.content)
                hash = await self.exec(  # noqa: A001
                    "git", "hash-object", "-w", "--stdin", input=r, capture=True
                )
                hash = await self.exec(  # noqa: A001
                    "git",
                    "mktree",
                    input=f"100644 blob {hash.strip()}\t{cfg.readme.name}\n",
                    capture=True,
                )
                hash = await self.exec(  # noqa: A001
                    "git", "commit-tree", hash.strip(), input="Migration README\n", capture=True
                )
                await self.exec("git", "branch", cfg.src.branch, hash.strip())

                if cfg.work.kill:
                    async with self.git_lock:
                        await self.exec(
                            "git",
                            "config",
                            "set",
                            "--append",
                            "remote.src.push",
                            f"refs/heads/{cfg.src.branch}",
                        )
                    # otherwise we push everything anyway
                # TODO update-or-add
            else:
                # check whether we're updating the README
                r = render(cfg.readme.content)
                hash = await self.exec("git", "hash-object", "--stdin", input=r, capture=True)  # noqa: A001
                hash2 = await self.exec(
                    "git", "ls-tree", cfg.src.branch, cfg.readme.name, capture=True
                )
                hash2 = hash2.split("\t", 1)[0]
                hash2 = hash2.split(" ", 2)[2]
                if hash.strip() != hash2:
                    await self.exec("git", "hash-object", "-w", "--stdin", input=r, capture=True)
                    hash = await self.exec(  # noqa: A001
                        "git",
                        "mktree",
                        input=f"100644 blob {hash.strip()}\t{cfg.readme.name}\n",
                        capture=True,
                    )
                    hash = await self.exec(  # noqa: A001
                        "git",
                        "commit-tree",
                        hash.strip(),
                        "-p",
                        cfg.src.branch,
                        capture=True,
                        input="Migration README update\n",
                    )
                    await self.exec("git", "branch", "-f", cfg.src.branch, hash.strip())

            await self.exec("git", "push", "src", cfg.src.branch)
            await src_repo.set_default_branch(cfg.src.branch)

        if cfg.work.kill:
            # Remove branches and tags from the source
            async with anyio.create_task_group() as tg:

                @tg.start_soon
                async def drop_branches():
                    branches = []
                    async for br in src_repo.get_branches():
                        brn = br.data.name
                        if brn != cfg.src.get("branch", ""):
                            branches.append(brn)
                    await src_repo.drop_branches(*branches)

                @tg.start_soon
                async def drop_tags():
                    tags = []
                    async for ta in src_repo.get_tags():
                        tags.append(ta["name"])
                    await src_repo.drop_tags(*tags)


async def _mv_repo(cfg: dict, a_src: API, a_dst: list[API], name: str):
    rm = RepoMover(cfg, name)
    rm.repos.src = ri = a_src.repo_info_for(rm)
    await ri.load(create=False)
    await rm.setup()

    for d in a_dst:
        rm.repos[d.name] = ri = d.repo_info_for(rm)
        await ri.load(create=None)

    rm.repos[d.name] = ri = d.repo_info_for(rm)
    for k, v in rm.repos.items():
        if k != "src":
            await rm.move(v)
    await rm.finish()


async def _mv_arepo(
    cfg: dict,
    a_src: API,
    a_dst: list[API],
    lim: anyio.CapacityLimiter,
    name: str,
    filter: bool,  # noqa: A002
):
    # move, then release the capacity limiter
    srci = None
    try:
        print(name)
        if filter:
            srci = await a_src.get_repo(name)
            if srci.parent:
                return
        await _mv_repo(cfg, a_src, a_dst, name)
    finally:
        lim.release_on_behalf_of(name)


async def mv_repo(cfg, name):
    """Move one repo off Github."""

    async with apis(cfg) as (a_src, *a_dst):
        await _mv_repo(cfg, a_src, a_dst, name)


@asynccontextmanager
async def apis(cfg) -> list[RepoInfo]:
    "Async context for our APIs"
    async with AsyncExitStack() as ex:
        res = [await ex.enter_async_context(get_api(cfg["src"], "src"))]
        for k, v in cfg.work.to.items():
            if v:
                res.append(await ex.enter_async_context(get_api(cfg[k], k)))
        yield res


async def mv_repos(cfg: dict, all: bool = False, names: list[str] = ()):  # noqa: A002
    """Move many repos off Github.

    @all: if False, don't touch repos that have a parent.
    """

    limiter = anyio.CapacityLimiter(cfg.work.parallel)

    async with (
        apis(cfg) as (a_src, *a_dst),
        anyio.create_task_group() as tg,
    ):
        if names:
            for n in names:
                await limiter.acquire_on_behalf_of(n)
                tg.start_soon(_mv_arepo, cfg, a_src, a_dst, limiter, n, False)
        else:
            async for n in a_src.list_repos():
                await limiter.acquire_on_behalf_of(n)
                tg.start_soon(_mv_arepo, cfg, a_src, a_dst, limiter, n, not all)
