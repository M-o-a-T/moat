"""Tests for the top-level SPKG verbs: ``add``, ``at SPKG``, ``set``, ``delete``."""

from __future__ import annotations

import asyncclick as click

from moat.src.test import raises as _raises


def _msg(err) -> str:
    """Lowercased message of a caught UsageError."""
    return str(err.value).lower()


async def test_add_and_list(src):
    """Adding a SPKG makes it appear in the list."""
    await src("add", "moat-util", "--comment", "Utility lib", "--prefix", "mu")
    res = await src("list")
    assert "moat-util" in res.stdout


async def test_add_duplicate_raises(src):
    """Re-adding an existing SPKG raises a UsageError mentioning 'already'."""
    await src("add", "dup")
    with _raises(click.UsageError) as err:
        await src("add", "dup")
    assert "already" in _msg(err)


async def test_at_unknown_points_at_add(src):
    """Scoping an unknown SPKG raises a UsageError pointing at ``add``."""
    with _raises(click.UsageError) as err:
        await src("at", "nosuch")
    assert "add" in _msg(err)


async def test_at_detail_dumps_prefix(src):
    """``at SPKG`` (no subcommand) dumps the package incl. ``prefix``."""
    await src("add", "p1", "--prefix", "pp")
    res = await src("at", "p1")
    assert "p1" in res.stdout
    assert "pp" in res.stdout


async def test_set_updates_comment_and_prefix(src):
    """``at SPKG set`` mutates the package."""
    await src("add", "p2", "--comment", "old")
    await src("at", "p2", "set", "--comment", "new", "--prefix", "p2p")
    res = await src("at", "p2")
    assert "new" in res.stdout
    assert "p2p" in res.stdout


async def test_prefix_clear_round_trip(src):
    """``--prefix -`` clears the prefix and the dump reflects it."""
    await src("add", "p3", "--prefix", "xx")
    await src("at", "p3", "set", "--prefix", "-")
    res = await src("at", "p3")
    # Cleared scalar columns are omitted from the dump (None-valued).
    assert "xx" not in res.stdout


async def test_delete_removes_spkg(src):
    """Deleting a SPKG drops it from the list."""
    await src("add", "gone")
    await src("at", "gone", "delete")
    res = await src("list")
    assert "gone" not in res.stdout
