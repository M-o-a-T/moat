"""Shared helpers for the ``moat db rain`` subcommands.

This module's name starts with ``_`` so the subcommand loader (which
skips underscore-prefixed modules) never exposes it as a command.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime

import asyncclick as click
from sqlalchemy import select

from moat.util import NotGiven
from moat.db.rain.model import Controller, Site, Valve
from moat.lib.run import option_ng

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator


def site_of(obj):
    """Resolve the currently-selected site (``obj.site_name``) to a row.

    Raises:
        click.UsageError: if the named site does not exist.
    """
    try:
        return obj.session.one(Site, name=obj.site_name)
    except KeyError:
        raise click.UsageError(f"Site {obj.site_name!r} doesn't exist.") from None


def require_name(obj, what: str) -> str:
    """Return ``obj.name`` or raise a usage error.

    Args:
        obj: The click object carrying the selected entity name.
        what: Human-readable entity name for the error message.
    """
    name = obj.name
    if name is None:
        raise click.UsageError(f"The {what} needs a name. Use '--name'.")
    return name


def get_one(obj, model, what: str, **kw):
    """Fetch a single ``model`` row matching ``kw`` or raise.

    Args:
        obj: The click object carrying the session.
        model: The mapped class to query.
        what: Human-readable entity name for the error message.
        **kw: Filter keyword arguments forwarded to :meth:`Mgr.one`.

    Raises:
        click.UsageError: if no row matches.
    """
    try:
        return obj.session.one(model, **kw)
    except KeyError:
        raise click.UsageError(f"This {what} doesn't exist.") from None


def absent(obj, model, what: str, **kw) -> None:
    """Raise if a ``model`` row matching ``kw`` already exists.

    Args:
        obj: The click object carrying the session.
        model: The mapped class to query.
        what: Human-readable entity name for the error message.
        **kw: Filter keyword arguments forwarded to :meth:`Mgr.one`.

    Raises:
        click.UsageError: if a matching row exists.
    """
    try:
        obj.session.one(model, **kw)
    except KeyError:
        return
    raise click.UsageError(f"This {what} already exists.") from None


def list_in_site(obj, model):
    """Iterate the rows of ``model`` belonging to the selected site."""
    site = site_of(obj)
    with obj.session.execute(select(model).where(model.site == site).order_by(model.name)) as rs:
        for (row,) in rs:
            yield row


def list_global(obj, model):
    """Iterate every row of ``model`` (for globally-scoped entities).

    Args:
        obj: The click object carrying the session.
        model: The mapped class to query; must have a ``name`` column.
    """
    with obj.session.execute(select(model).order_by(model.name)) as rs:
        for (row,) in rs:
            yield row


def valve_spec(obj, spec: str):
    """Resolve a ``controller:name`` valve spec to a :class:`Valve` row.

    Args:
        obj: The click object carrying the session and site name.
        spec: A ``controller:name`` string identifying the valve.

    Raises:
        click.UsageError: if the spec is malformed or the valve is absent.
    """
    try:
        ctrl_name, vname = spec.split(":", 1)
    except ValueError:
        raise click.UsageError(f"Bad valve spec {spec!r}; use 'controller:name'.") from None
    ctrl = get_one(obj, Controller, "controller", site=site_of(obj), name=ctrl_name)
    return get_one(obj, Valve, "valve", controller=ctrl, name=vname)


def is_given(v) -> bool:
    """True unless ``v`` is the ``NotGiven`` sentinel."""
    return v is not NotGiven


def parse_dt(s: str) -> datetime:
    """Parse an ISO-8601 timestamp, forcing timezone awareness.

    Naive timestamps are interpreted in the local timezone, matching the
    repo-wide convention of tz-aware datetimes everywhere.

    Raises:
        click.UsageError: if ``s`` is not a parseable timestamp.
    """
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise click.UsageError(f"Bad timestamp {s!r}.") from None
    if dt.tzinfo is None:
        dt = dt.astimezone()
    return dt


@contextmanager
def lookup_errors() -> Iterator[None]:
    """Translate :class:`Mgr.one` lookup failures into a :class:`UsageError`.

    ``apply()`` methods resolve parents and link targets by name via
    ``sess.one(Model, ...)``; a miss raises a bare ``KeyError``. This wraps
    such calls so the CLI surfaces a readable error instead of a traceback.
    """
    try:
        yield
    except KeyError as e:
        model, kw = e.args[0], e.args[1]
        name = kw.get("name")
        if name is not None:
            raise click.UsageError(f"{model.lower()} {name!r} doesn't exist.") from None
        raise click.UsageError(f"This {model.lower()} doesn't exist.") from None


def bool_pair(set_flag: bool, clr_flag: bool, key: str) -> dict:
    """Translate two mutually-exclusive set/clear flags into an apply arg.

    Args:
        set_flag: True if the "set" flag was passed.
        clr_flag: True if the "clear" flag was passed.
        key: The column name to set.

    Returns:
        ``{key: True}``, ``{key: False}``, or ``{}`` if neither flag was given.

    Raises:
        click.UsageError: if both flags were passed at once.
    """
    if set_flag and clr_flag:
        raise click.UsageError(f"--{key} and --no-{key} are mutually exclusive.")
    if set_flag:
        return {key: True}
    if clr_flag:
        return {key: False}
    return {}


def site_opts(c):
    """Decorator: the scalar options of a :class:`Site`."""
    c = option_ng("--name", "-n", type=str, help="Rename this site")(c)
    c = option_ng("--comment", "-c", type=str, help="Free-form description")(c)
    c = option_ng("--rate", "-r", "rate", type=float, help="Default watering rate (mm/h)")(c)
    c = option_ng("--rain-delay", "-d", "rain_delay", type=int, help="Pause after rain (seconds)")(
        c
    )
    return c
