"""Tests for ``moat.src.move``.

These tests exercise the :class:`RepoMover` helper methods
(:meth:`_ensure_push_refspec`, :meth:`create_workspace`) using
monkeypatched ``exec`` so no real git operations are needed.
"""

from __future__ import annotations

import pytest
import subprocess

from moat.util import attrdict
from moat.src.move import RepoMover

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

ProcErr = subprocess.CalledProcessError


def _make_rm(tmp_path: Path) -> RepoMover:
    """Construct a minimal :class:`RepoMover` for testing."""
    cfg = attrdict(
        cache=str(tmp_path),
        branch="main",
        src=attrdict(branch="migrated"),
        work=attrdict(kill=True, migrate=True, main=True, moved=False, workspace=False),
        readme=attrdict(name="README.md", content="# Moved\n"),
    )
    rm = RepoMover(cfg, "test-repo")
    return rm


@pytest.mark.anyio
async def test_ensure_push_refspec_adds_when_missing(monkeypatch, tmp_path):
    """Refspec is appended when not yet present."""
    rm = _make_rm(tmp_path)
    calls: list[tuple[tuple[object, ...], dict]] = []

    async def fake_exec(*cmd, **_kw):
        calls.append((cmd, _kw))
        if cmd[:3] == ("git", "config", "--get-all"):
            raise ProcErr(1, ["git", "config", "--get-all"])
        return None

    monkeypatch.setattr(rm, "exec", fake_exec)

    await rm._ensure_push_refspec("migrated")  # noqa:SLF001

    append_calls = [
        c
        for c, _ in calls
        if c[:4] == ("git", "config", "set", "--append") and c[4] == "remote.src.push"
    ]
    assert len(append_calls) == 1
    assert append_calls[0][5] == "refs/heads/migrated"


@pytest.mark.anyio
async def test_ensure_push_refspec_skips_when_present(monkeypatch, tmp_path):
    """Refspec is NOT appended when already present."""
    rm = _make_rm(tmp_path)
    calls: list[tuple[tuple[object, ...], dict]] = []

    async def fake_exec(*cmd, **_kw):
        calls.append((cmd, _kw))
        if cmd[:3] == ("git", "config", "--get-all"):
            return "refs/heads/migrated\n"
        return None

    monkeypatch.setattr(rm, "exec", fake_exec)

    await rm._ensure_push_refspec("migrated")  # noqa:SLF001

    append_calls = [c for c, _ in calls if c[:4] == ("git", "config", "set", "--append")]
    assert len(append_calls) == 0


@pytest.mark.anyio
async def test_ensure_push_refspec_idempotent(monkeypatch, tmp_path):
    """Calling twice does not add duplicate refspecs."""
    rm = _make_rm(tmp_path)
    refspecs: list[str] = []

    async def fake_exec(*cmd, **_kw):
        if cmd[:3] == ("git", "config", "--get-all"):
            return "\n".join(refspecs) + ("\n" if refspecs else "")
        if cmd[:4] == ("git", "config", "set", "--append"):
            assert isinstance(cmd[5], str)
            refspecs.append(cmd[5])
        return None

    monkeypatch.setattr(rm, "exec", fake_exec)

    await rm._ensure_push_refspec("migrated")  # noqa:SLF001
    await rm._ensure_push_refspec("migrated")  # noqa:SLF001

    assert refspecs == ["refs/heads/migrated"]


@pytest.mark.anyio
async def test_create_workspace_already_exists(monkeypatch, tmp_path):
    """create_workspace returns early if the directory exists."""
    rm = _make_rm(tmp_path)

    ws_dir = tmp_path / "test-repo-ws"
    ws_dir.mkdir()

    clone_called: list[bool] = []

    async def fake_exec(*cmd, **_kw):
        if cmd[:2] == ("git", "clone"):
            clone_called.append(True)
        return None

    monkeypatch.setattr(rm, "exec", fake_exec)

    result = await rm.create_workspace()
    assert result == ws_dir
    assert len(clone_called) == 0


@pytest.mark.anyio
async def test_create_workspace_clones_and_checks_out(monkeypatch, tmp_path):
    """create_workspace performs a shared clone and checks out the default branch."""
    rm = _make_rm(tmp_path)
    calls: list[tuple[tuple[object, ...], dict]] = []

    async def fake_exec(*cmd, **_kw):
        calls.append((cmd, _kw))
        return None

    monkeypatch.setattr(rm, "exec", fake_exec)

    result = await rm.create_workspace()
    expected_ws = tmp_path / "test-repo-ws"

    assert result == expected_ws

    clone_calls = [c for c, _ in calls if c[:2] == ("git", "clone")]
    assert len(clone_calls) == 1
    assert "--shared" in clone_calls[0]

    checkout_calls = [c for c, _ in calls if c[:2] == ("git", "checkout")]
    assert len(checkout_calls) == 1
    assert calls[1][1].get("cwd") == str(expected_ws)


@pytest.mark.anyio
async def test_create_workspace_checkout_fallback(monkeypatch, tmp_path):
    """create_workspace tolerates a failed checkout (falls back to HEAD)."""
    rm = _make_rm(tmp_path)
    calls: list[tuple[tuple[object, ...], dict]] = []

    async def fake_exec(*cmd, **_kw):
        calls.append((cmd, _kw))
        if cmd[:2] == ("git", "checkout"):
            raise ProcErr(1, ["git", "checkout"])
        return None

    monkeypatch.setattr(rm, "exec", fake_exec)

    result = await rm.create_workspace()
    assert result == tmp_path / "test-repo-ws"
