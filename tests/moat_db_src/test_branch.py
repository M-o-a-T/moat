"""Tests for ``at SPKG branch`` (LocalBranch) CRUD, status parsing, stamping."""

from __future__ import annotations

import asyncclick as click

from moat.src.test import raises as _raises


async def test_branch_crud(src, seed_roles):  # noqa:ARG001
    """add/show/set/delete round-trip for a local branch."""
    await src("add", "bpkg")
    await src("at", "bpkg", "branch", "add", "main", "--role", "main", "--status", "tracking")
    res = await src("at", "bpkg", "branch", "show", "main")
    assert "main" in res.stdout
    assert "tracking" in res.stdout
    assert "main" in res.stdout  # role echoed

    await src("at", "bpkg", "branch", "set", "main", "--commit", "cafef00d")
    res = await src("at", "bpkg", "branch", "show", "main")
    assert "cafef00d" in res.stdout

    await src("at", "bpkg", "branch", "delete", "main")
    with _raises(click.UsageError):
        await src("at", "bpkg", "branch", "show", "main")


async def test_status_from_file(src, seed_roles, tmp_path):  # noqa:ARG001
    """``--status @file`` reads the status text from a file."""
    f = tmp_path / "note.txt"
    f.write_text("very long status\nspanning lines\n")
    await src("add", "fpkg")
    await src("at", "fpkg", "branch", "add", "dev", "--status", f"@{f}")
    res = await src("at", "fpkg", "branch", "show", "dev")
    assert "very long status" in res.stdout
    assert "spanning lines" in res.stdout


async def test_status_clear_drops_field(src, seed_roles):  # noqa:ARG001
    """``--status -`` clears the status; it disappears from the dump."""
    await src("add", "cpkg")
    await src("at", "cpkg", "branch", "add", "b", "--status", "hello")
    await src("at", "cpkg", "branch", "set", "b", "--status", "-")
    res = await src("at", "cpkg", "branch", "show", "b")
    assert "hello" not in res.stdout


async def test_updated_stamped_on_change_only(src, seed_roles):  # noqa:ARG001
    """``updated`` advances on status/commit change and holds steady otherwise."""
    await src("add", "upkg")
    await src("at", "upkg", "branch", "add", "m", "--status", "s1")
    res1 = await src("at", "upkg", "branch", "show", "m")
    assert "updated" in res1.stdout

    # No-op set (same status) should not advance `updated`.
    await src("at", "upkg", "branch", "set", "m", "--status", "s1")
    res2 = await src("at", "upkg", "branch", "show", "m")
    assert (
        res2.stdout.split("updated:", 1)[1].splitlines()[0]
        == res1.stdout.split("updated:", 1)[1].splitlines()[0]
    )

    # Changing status advances `updated`.
    await src("at", "upkg", "branch", "set", "m", "--status", "s2")
    res3 = await src("at", "upkg", "branch", "show", "m")
    assert (
        res3.stdout.split("updated:", 1)[1].splitlines()[0]
        != res1.stdout.split("updated:", 1)[1].splitlines()[0]
    )


async def test_role_assign_and_clear(src, seed_roles):  # noqa:ARG001
    """``--role`` assigns a BranchRole; ``--role -`` clears it."""
    await src("add", "rpk")
    await src("at", "rpk", "branch", "add", "rel", "--role", "main")
    res = await src("at", "rpk", "branch", "show", "rel")
    assert "main" in res.stdout
    await src("at", "rpk", "branch", "set", "rel", "--role", "-")
    res = await src("at", "rpk", "branch", "show", "rel")
    # role cleared → 'null' in the dump
    assert "null" in res.stdout


async def test_branch_list(src, seed_roles):  # noqa:ARG001
    """Branches appear in the list with their role (or '-' if unset)."""
    await src("add", "lpkg")
    await src("at", "lpkg", "branch", "add", "main", "--role", "main")
    await src("at", "lpkg", "branch", "add", "topic")
    res = await src("at", "lpkg", "branch", "list")
    assert "main\tmain" in res.stdout
    assert "topic\t-" in res.stdout
