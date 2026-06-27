"""End-to-end CLI tests for ``moat db rain`` (site + controller CRUD).

Drives the full ``moat`` command line via :func:`moat.src.test.run`,
redirecting ``moat.db.url`` at a throwaway SQLite database so the tests
need no real server. Each test gets its own database (``tmp_path``).
"""

from __future__ import annotations

import pytest

import asyncclick as click

from moat.src.test import raises as _raises
from moat.src.test import run

pytestmark = pytest.mark.anyio


@pytest.fixture
async def rain(tmp_path):
    """A freshly-initialised temp SQLite DB, with an async ``R()`` caller."""
    url = f"sqlite:///{tmp_path}/r.db"
    await run("-s", "moat.db.url", url, "db", "init")

    async def R(*args, ee=0):
        return await run("-s", "moat.db.url", url, *args, expect_exit=ee)

    return R


def _msg(err) -> str:
    """Lowercased message of a caught UsageError."""
    return str(err.value).lower()


async def test_site_lifecycle(rain):
    """Create, list, show, modify, duplicate, and delete a site."""
    r = await rain("db", "rain", "-")
    assert r.stdout == ""

    r = await rain("db", "rain", "home", "add")
    assert "name: home" in r.stdout
    assert "rate: 10.0" in r.stdout
    assert "rain_delay: 300" in r.stdout

    r = await rain("db", "rain", "-")
    assert r.stdout == "home\n"

    r = await rain("db", "rain", "home")
    assert "name: home" in r.stdout

    r = await rain("db", "rain", "home", "set", "--rate", "20", "--comment", "hi")
    assert "rate: 20.0" in r.stdout
    assert "comment: hi" in r.stdout

    with _raises(click.UsageError) as err:
        await rain("db", "rain", "home", "add")
    assert "already exists" in _msg(err)

    await rain("db", "rain", "home", "delete")
    r = await rain("db", "rain", "-")
    assert r.stdout == ""


async def test_controller_lifecycle(rain):
    """Full controller CRUD plus the error paths."""
    await rain("db", "rain", "home", "add")

    r = await rain("db", "rain", "home", "controller", "-n", "C1", "add", "-l", "shed")
    assert "name: C1" in r.stdout
    assert "location: shed" in r.stdout
    assert "max_on: 3" in r.stdout

    r = await rain("db", "rain", "home", "controller", "show")
    assert r.stdout == "C1\n"

    r = await rain("db", "rain", "home", "controller", "-n", "C1", "show")
    assert "name: C1" in r.stdout

    r = await rain("db", "rain", "home", "controller", "-n", "C1", "set", "-c", "hi", "-m", "5")
    assert "comment: hi" in r.stdout
    assert "max_on: 5" in r.stdout
    assert "location: shed" in r.stdout  # untouched by `set`

    with _raises(click.UsageError) as err:
        await rain("db", "rain", "home", "controller", "-n", "C2", "add")
    assert "needs --location" in _msg(err)

    with _raises(click.UsageError) as err:
        await rain("db", "rain", "home", "controller", "-n", "C1", "add", "-l", "x")
    assert "already exists" in _msg(err)

    with _raises(click.UsageError) as err:
        await rain("db", "rain", "home", "controller", "-n", "Q", "show")
    assert "doesn't exist" in _msg(err)

    with _raises(click.UsageError) as err:
        await rain("db", "rain", "home", "controller", "-n", "Q", "set", "-l", "x")
    assert "doesn't exist" in _msg(err)

    with _raises(click.UsageError) as err:
        await rain("db", "rain", "home", "controller", "-n", "Q", "delete")
    assert "doesn't exist" in _msg(err)

    with _raises(click.UsageError) as err:
        await rain("db", "rain", "home", "controller", "add", "-l", "x")
    assert "needs a name" in _msg(err)

    await rain("db", "rain", "home", "controller", "-n", "C1", "delete")
    r = await rain("db", "rain", "home", "controller", "show")
    assert r.stdout == ""


async def test_dash_precludes_subcommands(rain):
    """``moat db rain - <verb>`` is rejected: '-' lists, it takes no verb."""
    with _raises(click.BadParameter):
        await rain("db", "rain", "-", "controller", "show")


async def test_missing_site(rain):
    """Operating on an unknown site fails cleanly."""
    with _raises(click.UsageError) as err:
        await rain("db", "rain", "nosuch", "controller", "-n", "C", "add", "-l", "x")
    assert "doesn't exist" in _msg(err)

    with _raises(click.UsageError) as err:
        await rain("db", "rain", "nosuch", "set", "--rate", "1")
    assert "doesn't exist" in _msg(err)

    with _raises(click.UsageError) as err:
        await rain("db", "rain", "nosuch", "delete")
    assert "doesn't exist" in _msg(err)


async def test_site_cascade_deletes_children(rain):
    """Deleting a site removes its controllers (FK CASCADE)."""
    await rain("db", "rain", "home", "add")
    await rain("db", "rain", "home", "controller", "-n", "C1", "add", "-l", "shed")
    await rain("db", "rain", "home", "controller", "-n", "C2", "add", "-l", "field")

    r = await rain("db", "rain", "home", "controller", "show")
    assert r.stdout == "C1\nC2\n"

    await rain("db", "rain", "home", "delete")
    await rain("db", "rain", "home", "add")  # recreate the site

    r = await rain("db", "rain", "home", "controller", "show")
    assert r.stdout == ""  # controllers cascaded away
