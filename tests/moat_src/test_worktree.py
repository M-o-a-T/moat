"""
Tests for ``moat.src.worktree``.
"""

from __future__ import annotations

import pytest
from pathlib import Path

import asyncclick as click

from moat.src import worktree


@pytest.mark.anyio
async def test_add_worktree_recurses(monkeypatch: pytest.MonkeyPatch) -> None:
    """Adding worktrees recurses through all nested submodules."""
    source = Path("/src/root")
    target = Path("/dst/root")

    status = {
        source: " 0 ext/a (heads/main)\n 1 ext/b (heads/main)\n",
        source / "ext/a": " 2 dep/c (heads/main)\n",
        source / "ext/a" / "dep/c": "",
        source / "ext/b": "",
    }
    calls: list[tuple[str, tuple[object, ...], Path | None, bool]] = []

    async def fake_run(
        *cmd: object, cwd: Path | None = None, capture: bool = False, **_kw: object
    ) -> str | None:
        calls.append((str(cmd[0]), cmd, cwd, capture))
        if cmd[:2] == ("git", "submodule"):
            assert cwd is not None
            return status[cwd]
        return None

    monkeypatch.setattr(worktree, "run_", fake_run)

    await worktree.add_worktree(source, "feat/x", target)

    add_calls = [c for c in calls if c[1][:3] == ("git", "worktree", "add")]
    assert add_calls == [
        (
            "git",
            ("git", "worktree", "add", "-b", "feat/x", "/dst/root/ext/a"),
            source / "ext/a",
            False,
        ),
        (
            "git",
            ("git", "worktree", "add", "-b", "feat/x", "/dst/root/ext/a/dep/c"),
            source / "ext/a" / "dep/c",
            False,
        ),
        (
            "git",
            ("git", "worktree", "add", "-b", "feat/x", "/dst/root/ext/b"),
            source / "ext/b",
            False,
        ),
    ]


@pytest.mark.anyio
async def test_delete_worktree_deep_first(monkeypatch: pytest.MonkeyPatch) -> None:
    """Deleting worktrees removes nested submodules before parents."""
    target = Path("/dst/root")
    status = {
        target: " 0 ext/a (heads/main)\n 1 ext/b (heads/main)\n",
        target / "ext/a": " 2 dep/c (heads/main)\n",
        target / "ext/a" / "dep/c": "",
        target / "ext/b": "",
    }
    calls: list[tuple[object, ...]] = []

    async def fake_run(
        *cmd: object, cwd: Path | None = None, capture: bool = False, **_kw: object
    ) -> str | None:
        calls.append((cmd, capture))
        if cmd[:2] == ("git", "submodule"):
            assert cwd is not None
            return status[cwd]
        return None

    monkeypatch.setattr(worktree, "run_", fake_run)

    await worktree.delete_worktree(target)

    rm_calls = [cmd for cmd, _capture in calls if cmd[:3] == ("git", "worktree", "remove")]
    assert rm_calls == [
        ("git", "worktree", "remove", "/dst/root/ext/a/dep/c"),
        ("git", "worktree", "remove", "/dst/root/ext/a"),
        ("git", "worktree", "remove", "/dst/root/ext/b"),
        ("git", "worktree", "remove", "/dst/root"),
    ]


@pytest.mark.anyio
async def test_fix_worktree_requires_existing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fixing requires an already existing top-level worktree."""
    source = Path("/src/root")
    target = Path("/dst/root")

    async def fake_run(
        *cmd: object, cwd: Path | None = None, capture: bool = False, **_kw: object
    ) -> str | None:
        if cmd[:3] == ("git", "worktree", "list"):
            assert cwd == source
            assert capture
            return "/src/root aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa [main]\n"
        raise RuntimeError(f"Unexpected command: {cmd}")

    monkeypatch.setattr(worktree, "run_", fake_run)

    with pytest.raises(click.ClickException, match="Not an existing worktree"):
        await worktree.fix_worktree(source, target)


@pytest.mark.anyio
async def test_fix_worktree_adds_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fixing adds only missing submodule worktrees using target base branch."""
    source = Path("/src/root")
    target = Path("/dst/root")

    status = {
        source: " 0 ext/a (heads/feat/y)\n 1 ext/b (heads/feat/y)\n",
        source / "ext/a": " 2 dep/c (heads/feat/y)\n",
        source / "ext/a" / "dep/c": "",
        source / "ext/b": "",
    }
    wt = {
        source: (
            "/src/root aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa [main]\n"
            "/dst/root bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb [feat/x]\n"
        ),
        source / "ext/a": "/src/root/ext/a cccccccccccccccccccccccccccccccccccccccc [main]\n",
        source
        / "ext/a"
        / "dep/c": "/src/root/ext/a/dep/c dddddddddddddddddddddddddddddddddddddddd [main]\n",
        source / "ext/b": (
            "/src/root/ext/b eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee [main]\n"
            "/dst/root/ext/b ffffffffffffffffffffffffffffffffffffffff [feat/x]\n"
        ),
    }
    calls: list[tuple[object, ...]] = []

    async def fake_run(
        *cmd: object, cwd: Path | None = None, capture: bool = False, **_kw: object
    ) -> str | None:
        calls.append(cmd)
        if cmd[:3] == ("git", "worktree", "list"):
            assert cwd is not None
            assert capture
            return wt[cwd]
        if cmd[:3] == ("git", "branch", "--show-current"):
            assert cwd == target
            assert capture
            return "feat/z\n"
        if cmd[:2] == ("git", "submodule"):
            assert cwd is not None
            assert capture
            return status[cwd]
        return None

    monkeypatch.setattr(worktree, "run_", fake_run)

    await worktree.fix_worktree(source, target)

    add_calls = [cmd for cmd in calls if cmd[:3] == ("git", "worktree", "add")]
    assert add_calls == [
        ("git", "worktree", "add", "-b", "feat/z", "/dst/root/ext/a"),
        ("git", "worktree", "add", "-b", "feat/z", "/dst/root/ext/a/dep/c"),
    ]
