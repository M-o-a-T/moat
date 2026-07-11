"""End-to-end CLI tests for ``moat db rain`` (site + controller CRUD).

Drives the full ``moat`` command line via :func:`moat.src.test.run`
against the shared SQLite database set up by the package
``conftest.py`` (one schema per session, ``rain_*`` rows wiped per test).
The standard test worlds are seeded by the ``seed_*`` fixtures there.
"""

from __future__ import annotations

import pytest

import asyncclick as click
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from moat.db.rain.model import Site
from moat.src.test import raises as _raises

pytestmark = pytest.mark.anyio


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


async def test_env_lifecycle(rain):
    """EnvGroup CRUD with the rain bool toggle and rename."""
    await rain("db", "rain", "home", "add")

    r = await rain("db", "rain", "home", "env", "-n", "std", "add", "--no-rain", "-f", "0.8")
    assert "name: std" in r.stdout
    assert "factor: 0.8" in r.stdout
    assert "rain: false" in r.stdout

    r = await rain("db", "rain", "home", "env", "show")
    assert r.stdout == "std\n"

    r = await rain("db", "rain", "home", "env", "-n", "std", "show")
    assert "rain: false" in r.stdout

    r = await rain("db", "rain", "home", "env", "-n", "std", "set", "--rain", "-f", "1.0")
    assert "rain: true" in r.stdout
    assert "factor: 1.0" in r.stdout

    r = await rain("db", "rain", "home", "env", "-n", "std", "set", "-n", "default")
    assert "name: default" in r.stdout
    r = await rain("db", "rain", "home", "env", "show")
    assert r.stdout == "default\n"

    with _raises(click.UsageError) as err:
        await rain("db", "rain", "home", "env", "-n", "default", "add")
    assert "already exists" in _msg(err)

    await rain("db", "rain", "home", "env", "-n", "default", "delete")
    r = await rain("db", "rain", "home", "env", "show")
    assert r.stdout == ""


async def test_valve_lifecycle(rain, seed_site):  # noqa:ARG001
    """Valve CRUD over the (controller, name) key with parents + Path fields."""

    r = await rain("db", "rain", "home", "valve", "show")
    assert r.stdout == ""  # none yet (hint goes to stderr)

    r = await rain(
        "db",
        "rain",
        "home",
        "valve",
        "-c",
        "C1",
        "-n",
        "V1",
        "add",
        "-F",
        "F1",
        "-e",
        "std",
        "-l",
        "front",
        "--flow",
        "2",
        "--area",
        "10",
        "--command",
        "cmd.v1",
        "--state",
        "st.v1",
        "--priority",
    )
    assert "name: V1" in r.stdout
    assert "command: !P cmd.v1" in r.stdout
    assert "state: !P st.v1" in r.stdout
    assert "flow: 2.0" in r.stdout
    assert "area: 10.0" in r.stdout
    assert "priority: true" in r.stdout

    r = await rain("db", "rain", "home", "valve", "show")
    assert r.stdout == "C1:V1\n"

    r = await rain("db", "rain", "home", "valve", "-c", "C1", "-n", "V1", "show")
    assert "command: !P cmd.v1" in r.stdout

    # set: change flow, clear command (monitor-only), drop priority
    r = await rain(
        "db",
        "rain",
        "home",
        "valve",
        "-c",
        "C1",
        "-n",
        "V1",
        "set",
        "--flow",
        "3",
        "--command",
        "-",
        "--no-priority",
    )
    assert "flow: 3.0" in r.stdout
    assert "command" not in r.stdout  # cleared
    assert "priority: false" in r.stdout
    assert "state: !P st.v1" in r.stdout  # untouched

    # required-field errors
    with _raises(click.UsageError) as err:
        await rain(
            "db",
            "rain",
            "home",
            "valve",
            "-c",
            "C1",
            "-n",
            "V2",
            "add",
            "-e",
            "std",
            "-l",
            "x",
            "--flow",
            "1",
            "--area",
            "1",
        )
    assert "needs --feed" in _msg(err)

    with _raises(click.UsageError) as err:
        await rain(
            "db",
            "rain",
            "home",
            "valve",
            "-c",
            "C1",
            "-n",
            "V2",
            "add",
            "-F",
            "F1",
            "-l",
            "x",
            "--flow",
            "1",
            "--area",
            "1",
        )
    assert "needs --envgroup" in _msg(err)

    # required-scalar errors: one explicit case per missing field
    for label, args in [
        ("location", ["-F", "F1", "-e", "std", "--flow", "1", "--area", "1"]),
        ("flow", ["-F", "F1", "-e", "std", "-l", "x", "--area", "1"]),
        ("area", ["-F", "F1", "-e", "std", "-l", "x", "--flow", "1"]),
    ]:
        with _raises(click.UsageError) as err:
            await rain("db", "rain", "home", "valve", "-c", "C1", "-n", "V2", "add", *args)
        assert f"needs --{label}" in _msg(err)

    with _raises(click.UsageError) as err:
        await rain(
            "db",
            "rain",
            "home",
            "valve",
            "-n",
            "V2",
            "add",
            "-F",
            "F1",
            "-e",
            "std",
            "-l",
            "x",
            "--flow",
            "1",
            "--area",
            "1",
        )
    assert "needs --controller" in _msg(err)

    with _raises(click.UsageError) as err:
        await rain(
            "db",
            "rain",
            "home",
            "valve",
            "-c",
            "C1",
            "add",
            "-F",
            "F1",
            "-e",
            "std",
            "-l",
            "x",
            "--flow",
            "1",
            "--area",
            "1",
        )
    assert "needs a name" in _msg(err)

    with _raises(click.UsageError) as err:
        await rain(
            "db",
            "rain",
            "home",
            "valve",
            "-c",
            "C1",
            "-n",
            "V1",
            "add",
            "-F",
            "F1",
            "-e",
            "std",
            "-l",
            "x",
            "--flow",
            "1",
            "--area",
            "1",
        )
    assert "already exists" in _msg(err)

    # set / delete without --name
    with _raises(click.UsageError) as err:
        await rain("db", "rain", "home", "valve", "-c", "C1", "set", "--flow", "9")
    assert "needs a name" in _msg(err)

    with _raises(click.UsageError) as err:
        await rain("db", "rain", "home", "valve", "-c", "C1", "delete")
    assert "needs a name" in _msg(err)

    # --priority and --no-priority are mutually exclusive
    with _raises(click.UsageError) as err:
        await rain(
            "db",
            "rain",
            "home",
            "valve",
            "-c",
            "C1",
            "-n",
            "V1",
            "set",
            "--priority",
            "--no-priority",
        )
    assert "mutually exclusive" in _msg(err)

    # same name on a different controller is distinct
    await rain("db", "rain", "home", "controller", "-n", "C2", "add", "-l", "field")
    r = await rain(
        "db",
        "rain",
        "home",
        "valve",
        "-c",
        "C2",
        "-n",
        "V1",
        "add",
        "-F",
        "F1",
        "-e",
        "std",
        "-l",
        "back",
        "--flow",
        "2",
        "--area",
        "5",
    )
    assert "name: V1" in r.stdout

    r = await rain("db", "rain", "home", "valve", "show")
    assert r.stdout == "C1:V1\nC2:V1\n"

    await rain("db", "rain", "home", "valve", "-c", "C1", "-n", "V1", "delete")
    r = await rain("db", "rain", "home", "valve", "show")
    assert r.stdout == "C2:V1\n"


async def test_day_lifecycle(rain):
    """Global Day CRUD (site argument accepted but ignored)."""
    await rain("db", "rain", "home", "add")

    r = await rain("db", "rain", "home", "day", "show")
    assert r.stdout == ""  # none yet (hint goes to stderr)

    r = await rain("db", "rain", "home", "day", "-n", "workday", "add")
    assert "name: workday" in r.stdout
    await rain("db", "rain", "home", "day", "-n", "weekend", "add")

    r = await rain("db", "rain", "home", "day", "show")
    assert r.stdout == "weekend\nworkday\n"

    r = await rain("db", "rain", "home", "day", "-n", "workday", "show")
    assert "name: workday" in r.stdout

    r = await rain("db", "rain", "home", "day", "-n", "workday", "set", "-n", "wd")
    assert "name: wd" in r.stdout
    r = await rain("db", "rain", "home", "day", "show")
    assert "workday" not in r.stdout
    assert "wd" in r.stdout

    with _raises(click.UsageError) as err:
        await rain("db", "rain", "home", "day", "add")
    assert "needs a name" in _msg(err)

    with _raises(click.UsageError) as err:
        await rain("db", "rain", "home", "day", "-n", "weekend", "add")
    assert "already exists" in _msg(err)

    with _raises(click.UsageError) as err:
        await rain("db", "rain", "home", "day", "-n", "nope", "show")
    assert "doesn't exist" in _msg(err)

    await rain("db", "rain", "home", "day", "-n", "wd", "delete")
    r = await rain("db", "rain", "home", "day", "show")
    assert r.stdout == "weekend\n"


async def test_daytime_nested(rain):
    """DayTime fragments managed through the nested ``time`` subgroup."""
    await rain("db", "rain", "home", "add")
    await rain("db", "rain", "home", "day", "-n", "workday", "add")

    r = await rain("db", "rain", "home", "day", "-n", "workday", "time", "show")
    assert r.stdout == ""  # no fragments yet (hint goes to stderr)

    r = await rain("db", "rain", "home", "day", "-n", "workday", "time", "-d", "8:00-12:00", "add")
    assert "descr: 8:00-12:00" in r.stdout
    await rain("db", "rain", "home", "day", "-n", "workday", "time", "-d", "14:00-18:00", "add")

    r = await rain("db", "rain", "home", "day", "-n", "workday", "time", "show")
    assert r.stdout == "14:00-18:00\n8:00-12:00\n"

    r = await rain(
        "db", "rain", "home", "day", "-n", "workday", "time", "-d", "8:00-12:00", "show"
    )
    assert "descr: 8:00-12:00" in r.stdout

    r = await rain(
        "db",
        "rain",
        "home",
        "day",
        "-n",
        "workday",
        "time",
        "-d",
        "8:00-12:00",
        "set",
        "-d",
        "08:00-12:00",
    )
    assert "descr: 08:00-12:00" in r.stdout
    r = await rain("db", "rain", "home", "day", "-n", "workday", "time", "show")
    assert r.stdout == "08:00-12:00\n14:00-18:00\n"

    with _raises(click.UsageError) as err:
        await rain("db", "rain", "home", "day", "-n", "workday", "time", "add")
    assert "needs a description" in _msg(err)

    with _raises(click.UsageError) as err:
        await rain(
            "db", "rain", "home", "day", "-n", "workday", "time", "-d", "14:00-18:00", "add"
        )
    assert "already exists" in _msg(err)

    with _raises(click.UsageError) as err:
        await rain("db", "rain", "home", "day", "-n", "nope", "time", "-d", "x", "add")
    assert "doesn't exist" in _msg(err)

    with _raises(click.UsageError) as err:
        await rain("db", "rain", "home", "day", "time", "-d", "x", "add")
    assert "needs a name" in _msg(err)

    with _raises(click.UsageError) as err:
        await rain("db", "rain", "home", "day", "-n", "workday", "time", "set")
    assert "needs a description" in _msg(err)

    with _raises(click.UsageError) as err:
        await rain("db", "rain", "home", "day", "-n", "workday", "time", "delete")
    assert "needs a description" in _msg(err)

    await rain("db", "rain", "home", "day", "-n", "workday", "time", "-d", "08:00-12:00", "delete")
    r = await rain("db", "rain", "home", "day", "-n", "workday", "time", "show")
    assert r.stdout == "14:00-18:00\n"


async def test_dayrange_lifecycle(rain):
    """Global DayRange CRUD with day linking/unlinking."""
    await rain("db", "rain", "home", "add")
    await rain("db", "rain", "home", "day", "-n", "workday", "add")
    await rain("db", "rain", "home", "day", "-n", "weekend", "add")

    r = await rain(
        "db",
        "rain",
        "home",
        "dayrange",
        "-n",
        "alldays",
        "add",
        "--day",
        "workday",
        "--day",
        "weekend",
    )
    assert "name: alldays" in r.stdout

    r = await rain("db", "rain", "home", "dayrange", "-n", "alldays", "show")
    assert "name: alldays" in r.stdout

    r = await rain("db", "rain", "home", "dayrange", "show")
    assert r.stdout == "alldays\n"

    r = await rain(
        "db",
        "rain",
        "home",
        "dayrange",
        "-n",
        "alldays",
        "set",
        "--rm-day",
        "weekend",
        "--comment",
        "hello",
    )
    assert "comment: hello" in r.stdout

    r = await rain("db", "rain", "home", "dayrange", "-n", "alldays", "set", "-n", "everyday")
    assert "name: everyday" in r.stdout
    r = await rain("db", "rain", "home", "dayrange", "show")
    assert r.stdout == "everyday\n"

    with _raises(click.UsageError) as err:
        await rain("db", "rain", "home", "dayrange", "-n", "everyday", "add")
    assert "already exists" in _msg(err)

    with _raises(click.UsageError) as err:
        await rain("db", "rain", "home", "dayrange", "-n", "everyday", "set", "--day", "nope")
    assert "doesn't exist" in _msg(err)

    await rain("db", "rain", "home", "dayrange", "-n", "everyday", "delete")
    r = await rain("db", "rain", "home", "dayrange", "show")
    assert r.stdout == ""


async def test_valve_bad_parent_names(rain):
    """Bad feed/envgroup names surface as readable UsageErrors, not tracebacks."""
    await rain("db", "rain", "home", "add")
    await rain("db", "rain", "home", "controller", "-n", "C1", "add", "-l", "shed")
    await rain("db", "rain", "home", "feed", "-n", "F1", "add", "-f", "mon.flow")
    await rain("db", "rain", "home", "env", "-n", "std", "add")

    base = [
        "db",
        "rain",
        "home",
        "valve",
        "-c",
        "C1",
        "-n",
        "V",
        "add",
        "-l",
        "x",
        "--flow",
        "1",
        "--area",
        "1",
    ]

    with _raises(click.UsageError) as err:
        await rain(*base, "-F", "nope", "-e", "std")
    msg = _msg(err)
    assert "feed" in msg
    assert "doesn't exist" in msg

    with _raises(click.UsageError) as err:
        await rain(*base, "-F", "F1", "-e", "nope")
    msg = _msg(err)
    assert "envgroup" in msg
    assert "doesn't exist" in msg

    with _raises(click.UsageError) as err:
        await rain(
            "db",
            "rain",
            "home",
            "valve",
            "-c",
            "nope",
            "-n",
            "V",
            "add",
            "-F",
            "F1",
            "-e",
            "std",
            "-l",
            "x",
            "--flow",
            "1",
            "--area",
            "1",
        )
    msg = _msg(err)
    assert "controller" in msg
    assert "doesn't exist" in msg


async def test_group_lifecycle(rain, seed_group_world):  # noqa:ARG001
    """Group CRUD with valve and day-range M2M links."""

    r = await rain("db", "rain", "home", "group", "show")
    assert r.stdout == ""  # none yet (hint goes to stderr)

    r = await rain(
        "db",
        "rain",
        "home",
        "group",
        "-n",
        "G1",
        "add",
        "--valve",
        "C1:V1",
        "--valve",
        "C2:V2",
        "--day",
        "alldays",
        "--xday",
        "weekends",
        "--adj",
        "1.2",
        "-c",
        "main",
    )
    assert "name: G1" in r.stdout
    assert "adj: 1.2" in r.stdout
    assert "C1:V1" in r.stdout
    assert "C2:V2" in r.stdout
    assert "alldays" in r.stdout
    assert "weekends" in r.stdout

    r = await rain("db", "rain", "home", "group", "show")
    assert r.stdout == "G1\n"

    r = await rain("db", "rain", "home", "group", "-n", "G1", "show")
    assert "valves:" in r.stdout
    assert "days:" in r.stdout
    assert "xdays:" in r.stdout

    # set: drop a valve, add a day, drop an xday, change adj
    r = await rain(
        "db",
        "rain",
        "home",
        "group",
        "-n",
        "G1",
        "set",
        "--rm-valve",
        "C2:V2",
        "--day",
        "weekends",
        "--rm-xday",
        "weekends",
        "--adj",
        "1.0",
    )
    assert "C1:V1" in r.stdout
    assert "C2:V2" not in r.stdout
    assert "adj: 1.0" in r.stdout
    # days now has alldays + weekends; xdays empty
    assert r.stdout.count("weekends") >= 1  # in days

    # rename
    r = await rain("db", "rain", "home", "group", "-n", "G1", "set", "-n", "GG1")
    assert "name: GG1" in r.stdout
    r = await rain("db", "rain", "home", "group", "show")
    assert r.stdout == "GG1\n"

    with _raises(click.UsageError) as err:
        await rain("db", "rain", "home", "group", "add")
    assert "needs a name" in _msg(err)

    with _raises(click.UsageError) as err:
        await rain("db", "rain", "home", "group", "-n", "GG1", "add")
    assert "already exists" in _msg(err)

    with _raises(click.UsageError) as err:
        await rain("db", "rain", "home", "group", "-n", "nope", "show")
    assert "doesn't exist" in _msg(err)

    with _raises(click.UsageError) as err:
        await rain("db", "rain", "home", "group", "-n", "G2", "add", "--valve", "bad-spec")
    assert "bad valve spec" in _msg(err)

    with _raises(click.UsageError) as err:
        await rain("db", "rain", "home", "group", "-n", "G2", "add", "--valve", "C1:nope")
    assert "doesn't exist" in _msg(err)

    with _raises(click.UsageError) as err:
        await rain("db", "rain", "home", "group", "-n", "G2", "add", "--day", "nope")
    assert "doesn't exist" in _msg(err)

    await rain("db", "rain", "home", "group", "-n", "GG1", "delete")
    r = await rain("db", "rain", "home", "group", "show")
    assert r.stdout == ""


async def test_valve_overrides(rain, seed_valve):  # noqa:ARG001
    """ValveOverride nested subgroup CRUD, keyed by (valve, start)."""
    ts = "2030-01-01T12:00:00"

    r = await rain(
        "db",
        "rain",
        "home",
        "valve",
        "-c",
        "C1",
        "-n",
        "V1",
        "override",
        "-s",
        ts,
        "add",
        "--duration",
        "3600",
        "--run",
        "--name",
        "noon",
    )
    assert "running: true" in r.stdout
    assert "duration: 3600" in r.stdout
    assert "name: noon" in r.stdout

    r = await rain("db", "rain", "home", "valve", "-c", "C1", "-n", "V1", "override", "show")
    assert r.stdout == f"{ts}\n"

    r = await rain(
        "db", "rain", "home", "valve", "-c", "C1", "-n", "V1", "override", "-s", ts, "show"
    )
    assert "running: true" in r.stdout

    r = await rain(
        "db",
        "rain",
        "home",
        "valve",
        "-c",
        "C1",
        "-n",
        "V1",
        "override",
        "-s",
        ts,
        "set",
        "--no-run",
        "--duration",
        "1800",
    )
    assert "running: false" in r.stdout
    assert "duration: 1800" in r.stdout

    with _raises(click.UsageError) as err:
        await rain(
            "db",
            "rain",
            "home",
            "valve",
            "-c",
            "C1",
            "-n",
            "V1",
            "override",
            "-s",
            "2031-01-01T00:00:00",
            "add",
        )
    assert "needs --duration" in _msg(err)

    with _raises(click.UsageError) as err:
        await rain(
            "db",
            "rain",
            "home",
            "valve",
            "-c",
            "C1",
            "-n",
            "V1",
            "override",
            "add",
            "--duration",
            "3600",
        )
    assert "needs a start" in _msg(err)

    with _raises(click.UsageError) as err:
        await rain(
            "db",
            "rain",
            "home",
            "valve",
            "-c",
            "C1",
            "-n",
            "V1",
            "override",
            "-s",
            ts,
            "add",
            "--duration",
            "3600",
        )
    assert "already exists" in _msg(err)

    with _raises(click.UsageError) as err:
        await rain(
            "db", "rain", "home", "valve", "-c", "C1", "-n", "V1", "override", "-s", "bad", "show"
        )
    assert "bad timestamp" in _msg(err)

    await rain(
        "db", "rain", "home", "valve", "-c", "C1", "-n", "V1", "override", "-s", ts, "delete"
    )
    r = await rain("db", "rain", "home", "valve", "-c", "C1", "-n", "V1", "override", "show")
    assert r.stdout == ""

    with _raises(click.UsageError) as err:
        await rain("db", "rain", "home", "valve", "-c", "C1", "override", "show")
    assert "needs a name" in _msg(err)


async def test_valve_schedules(rain, seed_valve):  # noqa:ARG001
    """Schedule nested subgroup CRUD, keyed by (valve, start)."""
    ts = "2030-02-01T08:00:00"

    r = await rain(
        "db",
        "rain",
        "home",
        "valve",
        "-c",
        "C1",
        "-n",
        "V1",
        "schedule",
        "-s",
        ts,
        "add",
        "--duration",
        "600",
        "--forced",
    )
    assert "duration: 600" in r.stdout
    assert "forced: true" in r.stdout
    assert "seen: false" in r.stdout

    r = await rain("db", "rain", "home", "valve", "-c", "C1", "-n", "V1", "schedule", "show")
    assert r.stdout == f"{ts}\n"

    r = await rain(
        "db",
        "rain",
        "home",
        "valve",
        "-c",
        "C1",
        "-n",
        "V1",
        "schedule",
        "-s",
        ts,
        "set",
        "--seen",
        "--no-forced",
    )
    assert "seen: true" in r.stdout
    assert "forced: false" in r.stdout

    with _raises(click.UsageError) as err:
        await rain(
            "db",
            "rain",
            "home",
            "valve",
            "-c",
            "C1",
            "-n",
            "V1",
            "schedule",
            "-s",
            "2031-01-01T00:00:00",
            "add",
        )
    assert "needs --duration" in _msg(err)

    await rain(
        "db", "rain", "home", "valve", "-c", "C1", "-n", "V1", "schedule", "-s", ts, "delete"
    )
    r = await rain("db", "rain", "home", "valve", "-c", "C1", "-n", "V1", "schedule", "show")
    assert r.stdout == ""


async def test_valve_levels(rain, seed_valve):  # noqa:ARG001
    """Level nested subgroup CRUD, keyed by (valve, time)."""
    ts = "2030-03-01T10:00:00"

    r = await rain(
        "db",
        "rain",
        "home",
        "valve",
        "-c",
        "C1",
        "-n",
        "V1",
        "level",
        "-t",
        ts,
        "add",
        "--level",
        "5.5",
        "--flow",
        "2.0",
    )
    assert "level: 5.5" in r.stdout
    assert "flow: 2.0" in r.stdout

    r = await rain("db", "rain", "home", "valve", "-c", "C1", "-n", "V1", "level", "show")
    assert r.stdout == f"{ts}\n"

    r = await rain(
        "db",
        "rain",
        "home",
        "valve",
        "-c",
        "C1",
        "-n",
        "V1",
        "level",
        "-t",
        ts,
        "set",
        "--flow",
        "3.0",
        "--forced",
    )
    assert "flow: 3.0" in r.stdout
    assert "forced: true" in r.stdout

    with _raises(click.UsageError) as err:
        await rain(
            "db",
            "rain",
            "home",
            "valve",
            "-c",
            "C1",
            "-n",
            "V1",
            "level",
            "-t",
            "2031-01-01T00:00:00",
            "add",
        )
    assert "needs --level" in _msg(err)

    await rain("db", "rain", "home", "valve", "-c", "C1", "-n", "V1", "level", "-t", ts, "delete")
    r = await rain("db", "rain", "home", "valve", "-c", "C1", "-n", "V1", "level", "show")
    assert r.stdout == ""


async def test_group_overrides(rain, seed_group_world):  # noqa:ARG001
    """GroupOverride nested subgroup CRUD, keyed by (group, start)."""
    await rain("db", "rain", "home", "group", "-n", "G1", "add", "--valve", "C1:V1")
    ts = "2030-04-01T12:00:00"

    r = await rain(
        "db",
        "rain",
        "home",
        "group",
        "-n",
        "G1",
        "override",
        "-s",
        ts,
        "add",
        "--duration",
        "3600",
        "--allow",
        "--name",
        "hol",
    )
    assert "allowed: true" in r.stdout
    assert "name: hol" in r.stdout

    r = await rain("db", "rain", "home", "group", "-n", "G1", "override", "show")
    assert r.stdout == f"{ts}\n"

    r = await rain(
        "db",
        "rain",
        "home",
        "group",
        "-n",
        "G1",
        "override",
        "-s",
        ts,
        "set",
        "--no-allow",
        "--duration",
        "7200",
    )
    assert "allowed: false" in r.stdout
    assert "duration: 7200" in r.stdout

    with _raises(click.UsageError) as err:
        await rain(
            "db",
            "rain",
            "home",
            "group",
            "-n",
            "G1",
            "override",
            "-s",
            "2031-01-01T00:00:00",
            "add",
        )
    assert "needs --duration" in _msg(err)

    await rain("db", "rain", "home", "group", "-n", "G1", "override", "-s", ts, "delete")
    r = await rain("db", "rain", "home", "group", "-n", "G1", "override", "show")
    assert r.stdout == ""


async def test_group_adjusts(rain, seed_group_world):  # noqa:ARG001
    """GroupAdjust nested subgroup CRUD, keyed by (group, start)."""
    await rain("db", "rain", "home", "group", "-n", "G1", "add", "--valve", "C1:V1")
    ts = "2030-05-01T00:00:00"

    r = await rain(
        "db", "rain", "home", "group", "-n", "G1", "adjust", "-s", ts, "add", "--factor", "1.5"
    )
    assert "factor: 1.5" in r.stdout

    r = await rain("db", "rain", "home", "group", "-n", "G1", "adjust", "show")
    assert r.stdout == f"{ts}\n"

    r = await rain(
        "db", "rain", "home", "group", "-n", "G1", "adjust", "-s", ts, "set", "--factor", "2.0"
    )
    assert "factor: 2.0" in r.stdout

    with _raises(click.UsageError) as err:
        await rain(
            "db", "rain", "home", "group", "-n", "G1", "adjust", "-s", "2031-01-01T00:00:00", "add"
        )
    assert "needs --factor" in _msg(err)

    await rain("db", "rain", "home", "group", "-n", "G1", "adjust", "-s", ts, "delete")
    r = await rain("db", "rain", "home", "group", "-n", "G1", "adjust", "show")
    assert r.stdout == ""


async def test_history_lifecycle(rain):
    """History weather-sample CRUD, keyed by (site, time)."""
    await rain("db", "rain", "home", "add")
    ts = "2030-06-01T12:00:00"

    r = await rain(
        "db",
        "rain",
        "home",
        "history",
        "-t",
        ts,
        "add",
        "--rain",
        "1.5",
        "--temp",
        "22.0",
        "--sun",
        "800",
    )
    assert "rain: 1.5" in r.stdout
    assert "temp: 22.0" in r.stdout
    assert "sun: 800.0" in r.stdout

    r = await rain("db", "rain", "home", "history", "show")
    assert r.stdout == f"{ts}\n"

    r = await rain("db", "rain", "home", "history", "-t", ts, "show")
    assert "rain: 1.5" in r.stdout

    r = await rain("db", "rain", "home", "history", "-t", ts, "set", "--rain", "2.0")
    assert "rain: 2.0" in r.stdout

    with _raises(click.UsageError) as err:
        await rain("db", "rain", "home", "history", "add", "--rain", "1")
    assert "needs a time" in _msg(err)

    with _raises(click.UsageError) as err:
        await rain("db", "rain", "home", "history", "-t", ts, "add", "--rain", "1")
    assert "already exists" in _msg(err)

    await rain("db", "rain", "home", "history", "-t", ts, "delete")
    r = await rain("db", "rain", "home", "history", "show")
    assert r.stdout == ""


async def test_log_lifecycle(rain, seed_valve):  # noqa:ARG001
    """Log event-entry CRUD (id-keyed), with controller/valve tags."""

    r = await rain(
        "db",
        "rain",
        "home",
        "history",
        "log",
        "add",
        "--logger",
        "sched",
        "--text",
        "started V1",
        "-c",
        "C1",
    )
    assert "logger: sched" in r.stdout
    assert "text: started V1" in r.stdout
    log_id = r.stdout.split("id:")[1].split()[0]

    r = await rain("db", "rain", "home", "history", "log", "show")
    assert r.stdout == f"{log_id}\n"

    r = await rain("db", "rain", "home", "history", "log", "--id", log_id, "show")
    assert "text: started V1" in r.stdout

    r = await rain(
        "db",
        "rain",
        "home",
        "history",
        "log",
        "--id",
        log_id,
        "set",
        "--text",
        "started V1 ok",
        "--controller",
        "-",
    )
    assert "text: started V1 ok" in r.stdout

    r = await rain(
        "db",
        "rain",
        "home",
        "history",
        "log",
        "add",
        "--logger",
        "op",
        "--text",
        "manual",
        "--valve",
        "C1:V1",
    )
    assert "text: manual" in r.stdout

    with _raises(click.UsageError) as err:
        await rain("db", "rain", "home", "history", "log", "add", "--logger", "x")
    assert "needs --text" in _msg(err)

    with _raises(click.UsageError) as err:
        await rain("db", "rain", "home", "history", "log", "add", "--text", "x")
    assert "needs --logger" in _msg(err)

    with _raises(click.UsageError) as err:
        await rain("db", "rain", "home", "history", "log", "--id", "999", "show")
    assert "doesn't exist" in _msg(err)

    await rain("db", "rain", "home", "history", "log", "--id", log_id, "delete")
    r = await rain("db", "rain", "home", "history", "log", "show")
    assert log_id not in r.stdout


async def test_nested_key_errors_and_shows(rain, seed_valve):  # noqa:ARG001
    """Single-keyed show, set/delete without the key, and empty-list hints."""
    ts = "2030-07-01T06:00:00"

    # single named show for each valve-nested subgroup
    await rain(
        "db",
        "rain",
        "home",
        "valve",
        "-c",
        "C1",
        "-n",
        "V1",
        "override",
        "-s",
        ts,
        "add",
        "--duration",
        "60",
        "--run",
    )
    r = await rain(
        "db", "rain", "home", "valve", "-c", "C1", "-n", "V1", "override", "-s", ts, "show"
    )
    assert "running: true" in r.stdout

    await rain(
        "db",
        "rain",
        "home",
        "valve",
        "-c",
        "C1",
        "-n",
        "V1",
        "schedule",
        "-s",
        ts,
        "add",
        "--duration",
        "60",
    )
    r = await rain(
        "db", "rain", "home", "valve", "-c", "C1", "-n", "V1", "schedule", "-s", ts, "show"
    )
    assert "duration: 60" in r.stdout

    await rain(
        "db",
        "rain",
        "home",
        "valve",
        "-c",
        "C1",
        "-n",
        "V1",
        "level",
        "-t",
        ts,
        "add",
        "--level",
        "1.0",
    )
    r = await rain(
        "db", "rain", "home", "valve", "-c", "C1", "-n", "V1", "level", "-t", ts, "show"
    )
    assert "level: 1.0" in r.stdout

    # set / delete without the key → "needs a start/time"
    for verb in ("set", "delete"):
        with _raises(click.UsageError) as err:
            await rain("db", "rain", "home", "valve", "-c", "C1", "-n", "V1", "override", verb)
        assert "needs a start" in _msg(err)
        with _raises(click.UsageError) as err:
            await rain("db", "rain", "home", "valve", "-c", "C1", "-n", "V1", "schedule", verb)
        assert "needs a start" in _msg(err)
        with _raises(click.UsageError) as err:
            await rain("db", "rain", "home", "valve", "-c", "C1", "-n", "V1", "level", verb)
        assert "needs a time" in _msg(err)

    # cleanup empties the lists
    await rain(
        "db", "rain", "home", "valve", "-c", "C1", "-n", "V1", "override", "-s", ts, "delete"
    )
    await rain(
        "db", "rain", "home", "valve", "-c", "C1", "-n", "V1", "schedule", "-s", ts, "delete"
    )
    await rain("db", "rain", "home", "valve", "-c", "C1", "-n", "V1", "level", "-t", ts, "delete")
    for sub in ("override", "schedule", "level"):
        r = await rain("db", "rain", "home", "valve", "-c", "C1", "-n", "V1", sub, "show")
        assert r.stdout == ""


async def test_group_nested_key_errors_and_shows(rain, seed_group_world):  # noqa:ARG001
    """Single-keyed show, set/delete without key for group override/adjust."""
    await rain("db", "rain", "home", "group", "-n", "G1", "add", "--valve", "C1:V1")
    ts = "2030-08-01T06:00:00"

    await rain(
        "db",
        "rain",
        "home",
        "group",
        "-n",
        "G1",
        "override",
        "-s",
        ts,
        "add",
        "--duration",
        "60",
        "--allow",
    )
    r = await rain("db", "rain", "home", "group", "-n", "G1", "override", "-s", ts, "show")
    assert "allowed: true" in r.stdout

    await rain(
        "db", "rain", "home", "group", "-n", "G1", "adjust", "-s", ts, "add", "--factor", "1.0"
    )
    r = await rain("db", "rain", "home", "group", "-n", "G1", "adjust", "-s", ts, "show")
    assert "factor: 1.0" in r.stdout

    for verb in ("set", "delete"):
        with _raises(click.UsageError) as err:
            await rain("db", "rain", "home", "group", "-n", "G1", "override", verb)
        assert "needs a start" in _msg(err)
        with _raises(click.UsageError) as err:
            await rain("db", "rain", "home", "group", "-n", "G1", "adjust", verb)
        assert "needs a start" in _msg(err)

    await rain("db", "rain", "home", "group", "-n", "G1", "override", "-s", ts, "delete")
    await rain("db", "rain", "home", "group", "-n", "G1", "adjust", "-s", ts, "delete")
    for sub in ("override", "adjust"):
        r = await rain("db", "rain", "home", "group", "-n", "G1", sub, "show")
        assert r.stdout == ""


async def test_log_extras(rain, seed_valve):  # noqa:ARG001
    """Log: empty list, --timestamp, --valve clear, set/delete without id."""

    r = await rain("db", "rain", "home", "history", "log", "show")
    assert r.stdout == ""  # empty (hint to stderr)

    r = await rain(
        "db",
        "rain",
        "home",
        "history",
        "log",
        "add",
        "--logger",
        "sched",
        "--text",
        "hi",
        "--timestamp",
        "2030-09-01T00:00:00",
    )
    assert "logger: sched" in r.stdout
    log_id = r.stdout.split("id:")[1].split()[0]

    r = await rain(
        "db",
        "rain",
        "home",
        "history",
        "log",
        "--id",
        log_id,
        "set",
        "--valve",
        "C1:V1",
        "--text",
        "tagged",
    )
    assert "text: tagged" in r.stdout
    r = await rain("db", "rain", "home", "history", "log", "--id", log_id, "set", "--valve", "-")
    assert "text: tagged" in r.stdout

    for verb in ("set", "delete"):
        with _raises(click.UsageError) as err:
            await rain("db", "rain", "home", "history", "log", verb)
        assert "needs an id" in _msg(err)


async def test_add_without_key_and_history_set_delete(rain, seed_group_world):  # noqa:ARG001
    """Add without the key, history set/delete without time, log set --timestamp."""
    await rain("db", "rain", "home", "group", "-n", "G1", "add", "--valve", "C1:V1")

    # add without the key (scalars present, key absent)
    with _raises(click.UsageError) as err:
        await rain(
            "db",
            "rain",
            "home",
            "valve",
            "-c",
            "C1",
            "-n",
            "V1",
            "schedule",
            "add",
            "--duration",
            "60",
        )
    assert "needs a start" in _msg(err)
    with _raises(click.UsageError) as err:
        await rain(
            "db", "rain", "home", "valve", "-c", "C1", "-n", "V1", "level", "add", "--level", "1"
        )
    assert "needs a time" in _msg(err)
    with _raises(click.UsageError) as err:
        await rain(
            "db", "rain", "home", "group", "-n", "G1", "override", "add", "--duration", "60"
        )
    assert "needs a start" in _msg(err)
    with _raises(click.UsageError) as err:
        await rain("db", "rain", "home", "group", "-n", "G1", "adjust", "add", "--factor", "1")
    assert "needs a start" in _msg(err)

    # history set / delete without --time
    with _raises(click.UsageError) as err:
        await rain("db", "rain", "home", "history", "set", "--rain", "1")
    assert "needs a time" in _msg(err)
    with _raises(click.UsageError) as err:
        await rain("db", "rain", "home", "history", "delete")
    assert "needs a time" in _msg(err)

    # log set with --timestamp
    r = await rain("db", "rain", "home", "history", "log", "add", "--logger", "x", "--text", "y")
    log_id = r.stdout.split("id:")[1].split()[0]
    r = await rain(
        "db",
        "rain",
        "home",
        "history",
        "log",
        "--id",
        log_id,
        "set",
        "--timestamp",
        "2030-10-01T00:00:00",
        "--text",
        "z",
    )
    assert "text: z" in r.stdout


async def test_dummy_site_dash(rain):
    """The dummy site '-' lists sites, and is accepted by global subcommands."""
    # no sites yet: '-' lists nothing (hint to stderr), exit 0
    r = await rain("db", "rain", "-")
    assert r.stdout == ""

    # global day/dayrange accept '-' as a dummy site, with no site defined
    r = await rain("db", "rain", "-", "day", "show")
    assert r.stdout == ""
    r = await rain("db", "rain", "-", "day", "-n", "summer", "add")
    assert "name: summer" in r.stdout
    r = await rain("db", "rain", "-", "day", "show")
    assert r.stdout == "summer\n"

    r = await rain("db", "rain", "-", "dayrange", "show")
    assert r.stdout == ""
    r = await rain("db", "rain", "-", "dayrange", "-n", "rng", "add", "--day", "summer")
    assert "name: rng" in r.stdout
    r = await rain("db", "rain", "-", "dayrange", "show")
    assert r.stdout == "rng\n"

    # nested subgroup under a global command also tolerates '-'
    r = await rain("db", "rain", "-", "day", "-n", "summer", "time", "-d", "8-12", "add")
    assert "descr: 8-12" in r.stdout
    r = await rain("db", "rain", "-", "day", "-n", "summer", "time", "show")
    assert r.stdout == "8-12\n"

    # a site-scoped subcommand rejects the dummy site
    with _raises(click.UsageError) as err:
        await rain("db", "rain", "-", "controller", "show")
    assert "dummy for global commands only" in _msg(err)
    assert "controller" in _msg(err)

    # '-' still lists real sites once one exists
    await rain("db", "rain", "home", "add")
    r = await rain("db", "rain", "-")
    assert r.stdout == "home\n"


async def test_site_rate_units(rain, db_url):
    """``--rate`` is mm/day on the CLI; the stored column is mm/second."""
    r = await rain("db", "rain", "home", "add")
    assert "rate: 10.0" in r.stdout

    # set to 20 mm/day; the CLI echoes mm/day
    r = await rain("db", "rain", "home", "set", "--rate", "20")
    assert "rate: 20.0" in r.stdout

    # the stored column is mm/second
    eng = create_engine(db_url)
    try:
        with Session(eng) as sess:
            site = sess.scalars(select(Site).where(Site.name == "home")).one()
            assert site.rate == 20 / (24 * 3600)
    finally:
        eng.dispose()


async def test_gen_cli_runs(rain, seed_valve):  # noqa:ARG001
    """``moat db rain <site> gen`` runs and reports the valve count."""
    r = await rain("db", "rain", "home", "gen", "--no-save")
    assert "valves: 1" in r.stdout
    assert "schedules: 0" in r.stdout  # V1 sits at level 0 < start_level → nothing to do


async def test_gen_cli_verbose(rain, seed_valve):  # noqa:ARG001
    """``--verbose`` wires the stderr narration sink (covered, output unchecked)."""
    r = await rain("db", "rain", "home", "gen", "--verbose", "--no-save")
    assert "valves: 1" in r.stdout


async def test_recalc_cli_runs(rain, seed_valve):  # noqa:ARG001
    """``moat db rain <site> recalc`` runs and reports the valve count."""
    r = await rain("db", "rain", "home", "recalc", "--no-save")
    assert "valves: 1" in r.stdout
    assert "updated: 0" in r.stdout  # no level rows → nothing to recompute
