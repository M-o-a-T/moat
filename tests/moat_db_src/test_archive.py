"""Tests for ``at SPKG remote`` (Archive) CRUD and the single-default invariant."""

from __future__ import annotations

import asyncclick as click

from moat.src.test import raises as _raises


def _msg(err) -> str:
    """Lowercased message of a caught UsageError."""
    return str(err.value).lower()


async def test_remote_crud(src, seed_roles):  # noqa:ARG001
    """add/show/set/delete round-trip for a remote."""
    await src("add", "rpkg")
    await src(
        "at",
        "rpkg",
        "remote",
        "add",
        "gh",
        "--role",
        "upstream",
        "--url",
        "https://example/x.git",
        "--default",
    )
    res = await src("at", "rpkg", "remote", "show", "gh")
    assert "gh" in res.stdout
    assert "upstream" in res.stdout
    assert "https://example/x.git" in res.stdout

    await src("at", "rpkg", "remote", "set", "gh", "--comment", "prim")
    res = await src("at", "rpkg", "remote", "show", "gh")
    assert "prim" in res.stdout

    await src("at", "rpkg", "remote", "delete", "gh")
    with _raises(click.UsageError):
        await src("at", "rpkg", "remote", "show", "gh")


async def test_remote_requires_role_and_url(src, seed_roles):  # noqa:ARG001
    """Creating a remote without --role / --url raises a UsageError."""
    await src("add", "rpkg2")
    with _raises(click.UsageError) as err:
        await src("at", "rpkg2", "remote", "add", "gh", "--url", "https://x")
    assert "role" in _msg(err)
    with _raises(click.UsageError) as err:
        await src("at", "rpkg2", "remote", "add", "gh", "--role", "upstream")
    assert "url" in _msg(err)


async def test_second_default_clears_the_first(src, seed_roles):  # noqa:ARG001
    """Setting a second --default demotes the previous default."""
    await src("add", "rpkg3")
    await src(
        "at",
        "rpkg3",
        "remote",
        "add",
        "a",
        "--role",
        "upstream",
        "--url",
        "https://a",
        "--default",
    )
    await src(
        "at",
        "rpkg3",
        "remote",
        "add",
        "b",
        "--role",
        "mirror",
        "--url",
        "https://b",
        "--default",
    )
    res = await src("at", "rpkg3", "remote", "list")
    # Exactly one '*' marker (the second remote is now default).
    assert res.stdout.count("*") == 1
    assert "* b\t" in res.stdout


async def test_role_immutable_after_create(src, seed_roles):  # noqa:ARG001
    """Changing a remote's role after creation raises."""
    await src("add", "rpkg4")
    await src(
        "at",
        "rpkg4",
        "remote",
        "add",
        "gh",
        "--role",
        "upstream",
        "--url",
        "https://x",
    )
    with _raises(ValueError):
        await src("at", "rpkg4", "remote", "set", "gh", "--role", "mirror")


async def test_remote_list_marking(src, seed_roles):  # noqa:ARG001
    """The default remote is marked with '*' in the list."""
    await src("add", "rpkg5")
    await src(
        "at",
        "rpkg5",
        "remote",
        "add",
        "origin",
        "--role",
        "upstream",
        "--url",
        "https://o",
        "--default",
    )
    await src(
        "at",
        "rpkg5",
        "remote",
        "add",
        "aux",
        "--role",
        "local",
        "--url",
        "https://a",
    )
    res = await src("at", "rpkg5", "remote", "list")
    assert "* origin\t" in res.stdout
    assert " aux\t" in res.stdout  # non-default prefixed with space
