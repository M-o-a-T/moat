"""Tests for the global archive-role and branch-role registries."""

from __future__ import annotations

import asyncclick as click

from moat.src.test import raises as _raises


def _msg(err) -> str:
    """Lowercased message of a caught UsageError."""
    return str(err.value).lower()


# ---- ArchiveRole (the `archive` group) ----


async def test_archive_crud(src):
    """add/show/set/delete round-trip for an archive role."""
    await src("archive", "add", "custom", "--comment", "c", "--rank", "5")
    res = await src("archive", "show", "custom")
    assert "custom" in res.stdout
    assert "5" in res.stdout
    await src("archive", "set", "custom", "--rank", "2")
    res = await src("archive", "show", "custom")
    assert "2" in res.stdout
    await src("archive", "delete", "custom")
    with _raises(click.UsageError) as err:
        await src("archive", "show", "custom")
    assert "exist" in _msg(err)


async def test_archive_list(src):
    """Added archive roles appear in the list."""
    await src("archive", "add", "alpha", "--rank", "1")
    await src("archive", "add", "beta", "--rank", "2")
    res = await src("archive", "list")
    assert "alpha" in res.stdout
    assert "beta" in res.stdout


async def test_archive_duplicate_raises(src):
    """Re-adding an archive role raises."""
    await src("archive", "add", "dup-ar")
    with _raises(click.UsageError) as err:
        await src("archive", "add", "dup-ar")
    assert "already" in _msg(err)


# ---- BranchRole (the `branch` group) ----


async def test_branch_role_crud(src):
    """add/show/set/delete round-trip for a branch role."""
    await src("branch", "add", "hotfix", "--comment", "urgent")
    res = await src("branch", "show", "hotfix")
    assert "hotfix" in res.stdout
    await src("branch", "set", "hotfix", "--abstract")
    res = await src("branch", "show", "hotfix")
    assert "true" in res.stdout  # abstract: true
    await src("branch", "set", "hotfix", "--real")
    res = await src("branch", "show", "hotfix")
    assert "false" in res.stdout  # abstract flipped back
    await src("branch", "delete", "hotfix")
    with _raises(click.UsageError):
        await src("branch", "show", "hotfix")


async def test_branch_role_abstract_real_mutually_exclusive(src):
    """Passing both --abstract and --real raises."""
    await src("branch", "add", "both")
    with _raises(ValueError):
        await src("branch", "set", "both", "--abstract", "--real")


async def test_branch_role_list(src):
    """Added branch roles appear in the list."""
    await src("branch", "add", "rls")
    await src("branch", "add", "dev")
    res = await src("branch", "list")
    assert "rls" in res.stdout
    assert "dev" in res.stdout
