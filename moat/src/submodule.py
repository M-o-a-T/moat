"""
Manage external git repositories listed in ``versions.yaml`` under the ``ext`` key.

Each entry looks like::

    ext:
      micropython:
        github: M-o-a-T/micropython.git
        rev: <commit-hash>

Remote keys present in an entry are tried in the order they appear;
the first URL that git accepts is used.  Unknown keys are silently skipped.
"""

from __future__ import annotations

import anyio
import shutil
import subprocess
from pathlib import Path

import asyncclick as click

from moat.util import yload, yprint
from moat.util.exec import run as run_

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

# ---------------------------------------------------------------------------
# Remote registry
# ---------------------------------------------------------------------------

#: Mapping of YAML key → function that converts the key's value to a clone URL.
#: Add entries here to support additional hosting services.
REMOTES: dict[str, Callable[[str], str]] = {
    "url": lambda arg: arg,
    "github": lambda arg: f"https://github.com/{arg}",
}


def _remote_urls(info: dict) -> list[tuple[str, str]]:
    """Return ``[(key, url), …]`` for every known remote key found in *info*.

    Keys that are not in :data:`REMOTES` are silently skipped.
    Order follows the iteration order of *info*.
    """
    result: list[tuple[str, str]] = []
    for key, value in info.items():
        if key in REMOTES:
            result.append((key, REMOTES[key](value)))
    return result


# ---------------------------------------------------------------------------
# versions.yaml helpers
# ---------------------------------------------------------------------------


_versions = Path("versions.yaml")


def _load_ext() -> dict:
    """Load and return the ``ext`` section from ``versions.yaml``."""
    with _versions.open() as fh:
        data = yload(fh, attr=False)
    return data.get("ext", {})


def _save_ext(ext: dict) -> None:
    """Persist an updated ``ext`` section back into ``versions.yaml``."""
    with _versions.open() as fh:
        data = yload(fh, attr=False)
    data["ext"] = ext
    with _versions.open("w") as fh:
        yprint(data, fh)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.group
def cli() -> None:
    """Manage external git repositories declared in ``versions.yaml``."""


_EXT = anyio.Path("ext")


@cli.command("get")
async def get_cmd() -> None:
    """Check out each external repository into ext/<name>.

    Repositories are read from the ``ext`` section of ``versions.yaml``.
    Each entry may contain one or more remote keys (e.g. ``github``, ``url``);
    they are tried in order and the first URL that git accepts is used.
    Unknown keys are ignored.  A ``rev`` field (commit hash or ref) is
    required.

    If the target directory already exists the remote is fetched; otherwise
    the repository is cloned.  In both cases the working tree is checked out
    at the recorded ``rev``.  ``ext`` must be a symlink or directory created
    by ``make setup``.
    """
    base = _EXT
    await base.mkdir(parents=True, exist_ok=True)
    ext = _load_ext()

    for name, info in ext.items():
        candidates = _remote_urls(info)
        if not candidates:
            print(f"[{name}] no known remote key – skipping", flush=True)
            continue

        rev: str = info["rev"]
        dest = base / name
        existing = await (dest / ".git").exists()
        worked: str | None = None

        for key, url in candidates:
            try:
                if existing:
                    print(f"[{name}] fetching via {key}: {url}", flush=True)
                    await run_(
                        "git",
                        "-C",
                        str(dest),
                        "fetch",
                        url,
                        "moat",
                        capture=False,
                    )
                else:
                    print(f"[{name}] cloning via {key}: {url} → {dest}", flush=True)
                    await run_(
                        "git",
                        "clone",
                        url,
                        str(dest),
                        capture=False,
                    )
            except subprocess.CalledProcessError:
                print(f"[{name}]   ↳ failed, trying next remote …", flush=True)
                # A failed clone may leave a partial directory behind.
                if not existing and await dest.exists():
                    shutil.rmtree(str(dest))
            else:
                worked = url
                break

        if worked is None:
            raise RuntimeError(f"[{name}] all remotes failed: {[u for _, u in candidates]}")

        print(f"[{name}] checking out {rev[:12]}", flush=True)
        await run_(
            "git",
            "-C",
            str(dest),
            "checkout",
            "--detach",
            rev,
            capture=False,
        )
        await run_(
            "git",
            "-C",
            str(dest),
            "submodule",
            "update",
            "--init",
            capture=False,
        )

        pushed = False
        for pkey, purl in candidates:
            try:
                print(f"[{name}] pushing HEAD:moat via {pkey}", flush=True)
                await run_(
                    "git",
                    "-C",
                    str(dest),
                    "push",
                    purl,
                    "HEAD:moat",
                    capture=False,
                )
                pushed = True
            except subprocess.CalledProcessError:
                print(f"[{name}]   ↳ push to {purl!r} failed", flush=True)
        if not pushed:
            raise RuntimeError(
                f"[{name}] push failed on all remotes: {[u for _, u in candidates]}"
            )


async def check_ext_clean(base: anyio.Path, ext: dict) -> list[str]:
    """Return the names of external repositories that have uncommitted changes.

    Runs ``git status --porcelain --ignore-submodules=all`` in each repo
    directory.  Entries whose target directory is not a git repository are
    silently skipped.

    Args:
        base: Parent directory that contains one sub-directory per repo.
        ext: The ``ext`` mapping from ``versions.yaml``.

    Returns:
        List of repository names that are dirty.
    """
    dirty: list[str] = []
    for name in ext:
        dest = base / name
        if not await (dest / ".git").exists():
            continue
        raw = await run_(
            "git",
            "-C",
            str(dest),
            "status",
            "--porcelain",
            "--ignore-submodules=all",
            capture=True,
        )
        assert raw is not None
        if raw.strip():
            dirty.append(name)
    return dirty


async def collect_ext_revs(base: anyio.Path, ext: dict) -> bool:
    """Read the HEAD commit of each external repository and update *ext* in-place.

    For every entry in *ext*, the HEAD commit of ``base/<name>`` is read
    via ``git rev-parse HEAD`` and stored back into ``ext[name]["rev"]``.
    Entries whose target directory is not a git repository are skipped with
    a warning.

    Args:
        base: Parent directory that contains one sub-directory per repo.
        ext: The ``ext`` mapping from ``versions.yaml``, modified in-place.

    Returns:
        ``True`` if at least one ``rev`` value was updated.
    """
    changed = False
    for name, info in ext.items():
        dest = base / name
        if not await (dest / ".git").exists():
            print(f"[{name}] skipping – {dest} is not a git repository", flush=True)
            continue

        raw = await run_("git", "-C", str(dest), "rev-parse", "HEAD", capture=True)
        assert raw is not None
        head = raw.strip()

        old = info.get("rev", "")
        if head != old:
            info["rev"] = head
            changed = True
            print(f"[{name}] {old[:12] or '(none)'} → {head[:12]}", flush=True)
        else:
            print(f"[{name}] unchanged ({head[:12]})", flush=True)
    return changed


@cli.command("commit")
@click.option("-f", "--no-dirty", is_flag=True, help="don't check for dirtiness (DANGER)")
async def commit_cmd(no_dirty: bool) -> None:
    """Record the current HEAD of each external repository into ``versions.yaml``.

    For every entry in the ``ext`` section, the HEAD commit of
    ``ext/<name>`` is read via ``git rev-parse HEAD`` and written back
    to ``versions.yaml``.  ``ext`` must be a symlink or directory created
    by ``make setup``.

    Aborts if any repository has uncommitted changes, unless ``--no-dirty``
    is given.
    """
    base = _EXT
    ext = _load_ext()
    if not no_dirty:
        dirty = await check_ext_clean(base, ext)
        if dirty:
            raise click.ClickException("External repositories are not clean: " + " ".join(dirty))
    changed = await collect_ext_revs(base, ext)
    if changed:
        _save_ext(ext)
        print("versions.yaml updated.", flush=True)
    else:
        print("No changes.", flush=True)
