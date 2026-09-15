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


async def test_at_detail_human_view_shows_prefix(src):
    """``at SPKG`` (no subcommand) renders the human view incl. ``(prefix)``."""
    await src("add", "p1", "--prefix", "pp", "--comment", "c1")
    res = await src("at", "p1")
    assert "p1 (pp): c1" in res.stdout


async def test_at_detail_skips_prefix_when_equal_to_name(src):
    """The ``(prefix)`` is omitted when prefix == name."""
    await src("add", "same", "--prefix", "same")
    res = await src("at", "same")
    assert res.stdout.splitlines()[0] == "same"  # no '(same)' suffix


async def test_at_detail_yaml_flag_emits_raw_dump(src):
    """``-y`` switches to the raw YAML dump (machine view)."""
    await src("add", "yk", "--prefix", "yy")
    res = await src("at", "-y", "yk")
    # YAML view keys appear, not the human header.
    assert "name: yk" in res.stdout
    assert "prefix: yy" in res.stdout


async def test_at_detail_n_branches_caps_and_notes_rest(src, seed_roles):  # noqa:ARG001
    """``-n N`` caps the branch list and prints '(… and N more)'."""
    await src("add", "nb")
    for i in range(7):
        await src("at", "nb", "branch", "add", f"b{i}", "--status", f"s{i}")
    res = await src("at", "-n", "3", "nb")
    lines = [ln for ln in res.stdout.splitlines() if ln.startswith("  ") and "more" not in ln]
    assert len(lines) == 3
    assert "(… and 4 more)" in res.stdout


async def test_at_detail_n_zero_shows_all_branches(src, seed_roles):  # noqa:ARG001
    """``-n 0`` shows every branch."""
    await src("add", "nz")
    for i in range(7):
        await src("at", "nz", "branch", "add", f"b{i}")
    res = await src("at", "-n", "0", "nz")
    blines = [ln for ln in res.stdout.splitlines() if ln.startswith("  b")]
    assert len(blines) == 7
    assert "more" not in res.stdout


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
