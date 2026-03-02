"""
Manage source worktrees, including submodules.
"""

from __future__ import annotations

import re
from pathlib import Path

import asyncclick as click

from moat.util.exec import run as run_

_SUBMODULE_RE = re.compile(r"^[ +\-U]?[0-9a-fA-F]+\s+(.+?)(?:\s+\(.*\))?$")


def _normalize(base: Path, path: Path) -> Path:
    """Return a normalized absolute path for ``path`` relative to ``base``."""
    if path.is_absolute():
        return path.resolve()
    return (base / path).resolve()


def _submodule_paths(status: str) -> list[Path]:
    """Extract relative submodule paths from ``git submodule`` output."""
    res: list[Path] = []
    for line in status.splitlines():
        match = _SUBMODULE_RE.match(line.rstrip())
        if match is None:
            continue
        res.append(Path(match.group(1)))
    return res


async def _collect_submodules(base: Path, rel: Path = Path()) -> list[Path]:
    """Collect all submodule paths below ``base`` recursively."""
    status = await run_("git", "submodule", cwd=base, capture=True)
    res: list[Path] = []
    for sub in _submodule_paths(status):
        path = rel / sub
        res.append(path)
        res.extend(await _collect_submodules(base / sub, path))
    return res


async def add_worktree(source_root: Path, branch: str, target_root: Path) -> None:
    """Create a worktree and add matching worktrees for all submodules."""
    await run_("bd", "worktree", "create", "--branch", branch, str(target_root))
    for sub in await _collect_submodules(source_root):
        await run_(
            "git",
            "worktree",
            "add",
            "-b",
            branch,
            str(target_root / sub),
            cwd=source_root / sub,
        )


async def delete_worktree(target_root: Path) -> None:
    """Remove a worktree after recursively removing submodule worktrees."""
    subs = await _collect_submodules(target_root)
    subs.sort(key=lambda x: len(x.parts), reverse=True)
    for sub in subs:
        path = target_root / sub
        await run_("git", "worktree", "remove", str(path), cwd=path)
    await run_("git", "worktree", "remove", str(target_root))


@click.group(short_help="Manage source worktrees.")
async def cli() -> None:
    """Manage source worktrees, including submodule worktrees."""


@cli.command("list")
async def list_() -> None:
    """List all worktrees."""
    res = await run_("git", "worktree", "list", capture=True)
    click.echo(res, nl=False)


@cli.command("add")
@click.argument("branch", type=str)
@click.argument("directory", type=click.Path(file_okay=False, path_type=Path))
async def add_(branch: str, directory: Path) -> None:
    """Create a worktree and matching submodule worktrees."""
    source = Path.cwd()
    target = _normalize(source, directory)
    await add_worktree(source, branch, target)


@cli.command("delete")
@click.argument("directory", type=click.Path(file_okay=False, path_type=Path))
async def delete_(directory: Path) -> None:
    """Delete a worktree and all submodule worktrees inside it."""
    target = _normalize(Path.cwd(), directory)
    await delete_worktree(target)
