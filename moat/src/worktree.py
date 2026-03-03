"""
Manage source worktrees, including submodules.
"""

from __future__ import annotations

import re
from pathlib import Path

import asyncclick as click

from moat.lib.run import AliasedGroup
from moat.util.exec import run as run_

_SUBMODULE_RE = re.compile(r"^[ +\-U]?[0-9a-fA-F]+\s+(.+?)(?:\s+\((.*)\))?$")
_WORKTREE_RE = re.compile(r"^(.+?)\s+[0-9a-fA-F]{7,40}\s+(?:\[(.+)\]|\(detached HEAD\))$")


def _normalize(base: Path, path: Path) -> Path:
    """Return a normalized absolute path for ``path`` relative to ``base``."""
    if path.is_absolute():
        return path.resolve()
    return (base / path).resolve()


def _extract_branch(desc: str | None) -> str | None:
    """Extract a branch name from submodule info text."""
    if desc is None:
        return None
    if desc.startswith("heads/"):
        return desc[6:]
    if desc.startswith("remotes/"):
        parts = desc.split("/", 2)
        if len(parts) == 3:
            return parts[2]
    if "/" not in desc and desc:
        return desc
    return None


def _submodule_paths(status: str) -> list[Path]:
    """Extract submodule path+branch tuples from ``git submodule list`` output."""
    res: list[Path] = []
    for line in status.splitlines():
        match = _SUBMODULE_RE.match(line.rstrip())
        if match is None:
            parts = line.split(maxsplit=1)
            if len(parts) != 2:
                continue
            res.append(Path(parts[0]))
        else:
            res.append(Path(match.group(1)))
    return res


async def _read_submodule_list(base: Path, debug: int = 0) -> str | None:
    """Read submodule status/list information."""
    if not (base / ".git").exists():
        return ""
    return await run_("git", "submodule", cwd=base, capture=True, echo=debug > 1)


async def _collect_submodules(base: Path, rel: Path = Path(), debug: int = 0) -> list[Path]:
    """Collect all submodule paths below ``base`` recursively."""
    status = await _read_submodule_list(base, debug=debug)
    res: list[tuple[Path, str | None]] = []
    if status is not None:
        for sub in _submodule_paths(status):
            path = rel / sub
            res.append(path)
            res.extend(await _collect_submodules(base / sub, path, debug=debug))
    return res


async def add_worktree(source_root: Path, branch: str, target_root: Path, debug: int = 0) -> None:
    """Create a worktree and add matching worktrees for all submodules."""
    await run_("bd", "worktree", "create", "--branch", branch, str(target_root))
    for sub in await _collect_submodules(source_root, debug=debug):
        await run_(
            "git",
            "worktree",
            "add",
            "-B",
            branch,
            str(target_root / sub),
            cwd=source_root / sub,
            echo=bool(debug),
        )


async def delete_worktree(target_root: Path, debug: int = 0) -> None:
    """Remove a worktree after recursively removing submodule worktrees."""
    subs = [sub for sub in await _collect_submodules(target_root, debug=debug)]
    subs.sort(key=lambda x: len(x.parts), reverse=True)
    for sub in subs:
        path = target_root / sub
        await run_("git", "worktree", "remove", str(path), cwd=path, echo=bool(debug))
    await run_("git", "worktree", "remove", str(target_root), echo=bool(debug))


def _parse_worktree_list(data: str) -> dict[Path, str | None]:
    """Parse ``git worktree list`` output into ``path -> branch``."""
    res: dict[Path, str | None] = {}
    for line in data.splitlines():
        match = _WORKTREE_RE.match(line.rstrip())
        if match is None:
            continue
        path = Path(match.group(1)).resolve()
        res[path] = match.group(2)
    return res


async def _read_worktree_list(base: Path) -> dict[Path, str | None]:
    """Read worktree metadata for ``base``."""
    data = await run_("git", "worktree", "list", cwd=base, capture=True)
    return _parse_worktree_list(data)


async def _read_current_branch(base: Path, debug: int = 0) -> str | None:
    """Read the current branch name for ``base``."""
    branch = await run_("git", "branch", "--show-current", cwd=base, capture=True, echo=debug > 1)
    branch = branch.strip()
    if not branch:
        return None
    return branch


async def fix_worktree(source_root: Path, target_root: Path, debug: int = 0) -> None:
    """Add missing submodule worktrees to an existing top-level worktree."""
    worktrees = await _read_worktree_list(source_root)
    if target_root not in worktrees:
        raise click.ClickException(f"Not an existing worktree: {target_root}")
    branch = await _read_current_branch(target_root, debug=debug)
    if branch is None:
        raise click.ClickException(f"Cannot determine branch for worktree {target_root}")

    for sub in await _collect_submodules(source_root, debug=debug):
        source_sub = source_root / sub
        target_sub = target_root / sub
        sub_worktrees = await _read_worktree_list(source_sub)
        if target_sub in sub_worktrees:
            continue
        await run_(
            "git", "worktree", "add", "-b", branch, str(target_sub), cwd=source_sub, echo=debug > 0
        )


@click.group(cls=AliasedGroup, short_help="Manage source worktrees.")
async def cli() -> None:
    """Manage source worktrees, including submodule worktrees."""


@cli.command("list")
@click.pass_obj
async def list_(obj) -> None:
    """List all worktrees."""
    res = await run_("git", "worktree", "list", capture=True, echo=obj.debug > 2)
    click.echo(res, nl=False)


@cli.command("prune")
@click.pass_obj
async def prune_(obj) -> None:
    """Prune all worktrees."""
    source = Path.cwd()
    for sub in await _collect_submodules(source, debug=obj.debug - 1 if obj.debug > 0 else 0):
        await run_("git", "worktree", "prune", cwd=sub, echo=obj.debug > 2)
        if obj.debug == 2:
            print(sub)


@cli.command("submodules")
@click.pass_obj
async def submodules_(obj) -> None:
    """List all submodules."""
    source = Path.cwd()
    for sub in await _collect_submodules(source, debug=obj.debug - 1 if obj.debug > 0 else 0):
        print(sub)


@cli.command("add")
@click.argument("branch", type=str)
@click.argument("directory", type=click.Path(file_okay=False, path_type=Path))
@click.pass_obj
async def add_(obj, branch: str, directory: Path) -> None:
    """Create a worktree and matching submodule worktrees."""
    source = Path.cwd()
    target = _normalize(source, directory)
    await add_worktree(source, branch, target, debug=obj.debug - 1 if obj.debug > 0 else 0)


@cli.command("delete")
@click.argument("directory", type=click.Path(file_okay=False, path_type=Path))
@click.pass_obj
async def delete_(obj, directory: Path) -> None:
    """Delete a worktree and all submodule worktrees inside it."""
    target = _normalize(Path.cwd(), directory)
    await delete_worktree(target, debug=obj.debug - 1 if obj.debug > 0 else 0)


@cli.command("fix")
@click.argument("directory", type=click.Path(file_okay=False, path_type=Path))
@click.pass_obj
async def fix_(obj, directory: Path) -> None:
    """Add missing submodule worktrees to an existing worktree."""
    source = Path.cwd()
    target = _normalize(source, directory)
    await fix_worktree(source, target, debug=obj.debug - 1 if obj.debug > 0 else 0)
