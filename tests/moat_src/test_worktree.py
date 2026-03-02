"""
Tests for ``moat.src.worktree``.
"""

from __future__ import annotations

import pytest
from pathlib import Path

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
