"""
Code that migrates stuff from A to B.
"""

from __future__ import annotations

import io
import anyio
import logging
import subprocess
import sys
import re
from collections import defaultdict, deque
from configparser import RawConfigParser
from pathlib import Path
from copy import deepcopy
from packaging.version import Version

import asyncclick as click
import git
import tomlkit
from moat.util import P, add_repr, attrdict, make_proc, yload, yprint
from packaging.requirements import Requirement
from attrs import define, field
from shutil import rmtree, copyfile, copytree
from contextlib import suppress
from .api import get_api
import jinja2

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .api import API


logger = logging.getLogger(__name__)

async def _mv_repo(cfg:dict, a_src:API, a_dst: API, name:str, src_repo:RepoInfo|None):
    """Move one repo from A to B."""
    csrc = cfg["src"]
    cdst = cfg["dst"]

    if src_repo is None:
        src_repo = await a_src.get_repo(name)

    loc = anyio.Path(cfg.prefix) / name
    if not await loc.is_dir():
        logger.debug(f"Cloning %s", name)
        try:
            await src_repo.clone_to(loc, name="_move_origin")
        except BaseException:
            # XXX do this in Python instead
            with anyio.CancelScope(shield=True):
                await anyio.run_process(["/bin/rm","-rf","--",str(loc)])
            raise

    if not await (loc/".git").exists():
        raise RuntimeError(f"Incomplete clone of {name}")

    try:
        await anyio.run_process(["git","rev-parse","--verify","_moved_", cwd=str(loc)])
    except Exception as exc:
        logger.debug(f"Creating exit branch", name)

        e = jinja2.Environment(autoescape=False)
        t = e.compile(cfg.readme.content)
        r = t.render(dict())
        ior = io.StringIO()
        await anyio.run_process(["git","hash-object","-w","--stdin"], input=r, stdout=hsh, cwd=str(loc))

        hash = ior.getvalue().strip()
        ior.reset()
        await anyio.run_process(["git","mktree"], input=f"100644 blob {hash}\t{cfg.readme.name}\n", stdout=ior, cwd=str(loc))

        hash = ior.getvalue().strip()
        ior.reset()
        await anyio.run_process(["git","commit-tree", hash], stdout=ior, cwd=str(loc))
        hash = ior.getvalue().strip()
        await anyio.run_process(["git","branch", "_moved_", hash], cwd=str(loc))

    try:
        await src_repo.get_branch(src_repo.cfg.branch)
    except SyntaxError:
        await anyio.run_process(["git","push", "origin", f"_moved_:{src_repo.cfg.branch}"], cwd=str(loc))


    await src_repo.set_default_branch(src_repo.cfg.branch)

    if cfg.work.kill:
        async with anyio.create_task_group() as tg:
            @tg.start_soon
            async def drop_branches():
                branches = []
                async for br in src_repo.get_branches():
                    if br != src_repo.cfg.branch:
                        branches.append(br)
                for br in branches:
                    await src_repo.drop_branch(br)

            @tg.start_soon
            async def drop_tags():
                tags = []
                async for ta in src_repo.get_tags():
                    tags.append(ta)
                for ta in tags:
                    await src_repo.drop_branch(ta)

async def _mv_arepo(cfg:dict, a_src:API, a_dst: API, lim:anyio.CapacityLimiter, name:str, filter:bool):
    # move with capacity limiter release
    srci = None
    try:
        print(name)
        if filter:
            srci = await a_src.get_repo(name)
            if srci.parent:
                return
        await _mv_repo(cfg,a_src,a_dst,name,srci)
    finally:
        lim.release_on_behalf_of(name)

async def mv_repo(cfg, name):
    """Move one repo off Github."""

    csrc = cfg["src"]
    cdst = cfg["dst"]

    async with (
        get_api(csrc) as a_src,
        get_api(cdst) as a_dst,
    ):
        await _mv_repo(cfg,a_src,a_dst,name)

async def mv_repos(cfg:dict, all:bool=False, names:list[str] = ()):
    """Move many repos off Github."""

    limiter = anyio.CapacityLimiter(cfg.work.parallel)

    async with (
        anyio.create_task_group() as tg,
        get_api(cfg["src"]) as a_src,
        get_api(cfg["dst"]) as a_dst,
    ):
        if names:
            for n in names:
                await limiter.acquire_on_behalf_of(n)
                tg.start_soon(_mv_arepo, cfg, a_src, a_dst, limiter, n, False)
        else:
            async for n in a_src.list_repos():
                await limiter.acquire_on_behalf_of(n)
                tg.start_soon(_mv_arepo, cfg, a_src, a_dst, limiter, n, True)

