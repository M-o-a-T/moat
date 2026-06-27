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


async def test_feed_lifecycle(rain):
    """Feed CRUD with a Path field (flow_monitor) and disable/enable."""
    await rain("db", "rain", "home", "add")

    r = await rain("db", "rain", "home", "feed", "-n", "F1", "add", "-f", "mon.flow")
    assert "name: F1" in r.stdout
    assert "flow_monitor: !P mon.flow" in r.stdout
    assert "flow: 10.0" in r.stdout
    assert "disabled: false" in r.stdout

    r = await rain("db", "rain", "home", "feed", "show")
    assert r.stdout == "F1\n"

    r = await rain("db", "rain", "home", "feed", "-n", "F1", "show")
    assert "name: F1" in r.stdout

    r = await rain("db", "rain", "home", "feed", "-n", "F1", "set", "--flow", "5", "--disable")
    assert "flow: 5.0" in r.stdout
    assert "disabled: true" in r.stdout
    assert "flow_monitor: !P mon.flow" in r.stdout  # untouched

    r = await rain("db", "rain", "home", "feed", "-n", "F1", "set", "-f", "-")
    assert "flow_monitor" not in r.stdout  # cleared → omitted from dump

    r = await rain("db", "rain", "home", "feed", "-n", "F1", "set", "--enable")
    assert "disabled: false" in r.stdout

    with _raises(click.UsageError) as err:
        await rain("db", "rain", "home", "feed", "-n", "F1", "add")
    assert "already exists" in _msg(err)

    with _raises(click.UsageError) as err:
        await rain("db", "rain", "home", "feed", "-n", "Q", "show")
    assert "doesn't exist" in _msg(err)

    with _raises(click.UsageError) as err:
        await rain("db", "rain", "home", "feed", "add")
    assert "needs a name" in _msg(err)

    await rain("db", "rain", "home", "feed", "-n", "F1", "delete")
    r = await rain("db", "rain", "home", "feed", "show")
    assert r.stdout == ""


async def test_sensor_lifecycle(rain):
    """Sensor CRUD over the (site, kind, name) key; kind is immutable."""
    await rain("db", "rain", "home", "add")

    r = await rain("db", "rain", "home", "sensor", "show")
    assert r.stdout == ""  # none yet (hint goes to stderr)

    r = await rain(
        "db", "rain", "home", "sensor", "-k", "rain", "-n", "R1", "add", "-s", "sen.rain"
    )
    assert "kind: rain" in r.stdout
    assert "name: R1" in r.stdout
    assert "state: !P sen.rain" in r.stdout
    assert "weight: 10" in r.stdout

    r = await rain(
        "db", "rain", "home", "sensor", "-k", "temp", "-n", "T1", "add", "-s", "sen.temp"
    )
    assert "kind: temp" in r.stdout

    r = await rain("db", "rain", "home", "sensor", "show")
    assert r.stdout == "rain:R1\ntemp:T1\n"

    r = await rain("db", "rain", "home", "sensor", "-k", "rain", "show")
    assert r.stdout == "rain:R1\n"

    r = await rain("db", "rain", "home", "sensor", "-k", "rain", "-n", "R1", "show")
    assert "state: !P sen.rain" in r.stdout

    r = await rain("db", "rain", "home", "sensor", "-k", "rain", "-n", "R1", "set", "-w", "20")
    assert "weight: 20" in r.stdout

    with _raises(click.UsageError) as err:
        await rain("db", "rain", "home", "sensor", "-k", "wind", "-n", "W1", "add")
    assert "needs --state" in _msg(err)

    with _raises(click.UsageError) as err:
        await rain("db", "rain", "home", "sensor", "-n", "X", "add", "-s", "x.y")
    assert "needs --kind" in _msg(err)

    with _raises(click.UsageError) as err:
        await rain("db", "rain", "home", "sensor", "-n", "R1", "show")
    assert "needs --kind" in _msg(err)

    with _raises(click.UsageError) as err:
        await rain("db", "rain", "home", "sensor", "-k", "rain", "-n", "R1", "add", "-s", "x.y")
    assert "already exists" in _msg(err)

    # same name, different kind, is distinct
    r = await rain("db", "rain", "home", "sensor", "-k", "temp", "-n", "R1", "add", "-s", "sen.t2")
    assert "kind: temp" in r.stdout

    r = await rain("db", "rain", "home", "sensor", "show")
    assert r.stdout == "rain:R1\ntemp:R1\ntemp:T1\n"

    await rain("db", "rain", "home", "sensor", "-k", "rain", "-n", "R1", "delete")
    r = await rain("db", "rain", "home", "sensor", "show")
    assert r.stdout == "temp:R1\ntemp:T1\n"
