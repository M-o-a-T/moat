"""Shared helpers for the ``moat db rain`` subcommands.

This module's name starts with ``_`` so the subcommand loader (which
skips underscore-prefixed modules) never exposes it as a command.
"""

from __future__ import annotations

import asyncclick as click
from sqlalchemy import select

from moat.util import NotGiven
from moat.db.rain.model import Site
from moat.lib.run import option_ng


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


def is_given(v) -> bool:
    """True unless ``v`` is the ``NotGiven`` sentinel."""
    return v is not NotGiven


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
