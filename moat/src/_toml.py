"""
Get tomlkit and teach yaml about its classes.
"""

from __future__ import annotations

import tomlkit
import tomlkit.container
import tomlkit.items

from moat.util import add_repr

__all__ = ["get_array", "get_table", "tomlkit"]

add_repr(tomlkit.items.String)
add_repr(tomlkit.items.Integer)
add_repr(tomlkit.items.Bool, bool)
add_repr(tomlkit.items.AbstractTable)
add_repr(tomlkit.items.Array)


def get_table(
    parent: tomlkit.items.AbstractTable | tomlkit.container.Container | None,
    key: str,
) -> tomlkit.items.AbstractTable | None:
    """Return the tomlkit sub-table ``parent[key]``, or ``None``.

    tomlkit's ``__getitem__`` is typed as the loose ``Item | Container``
    union; this helper narrows it to a table for callers that rely on
    dict-like access.
    """
    if parent is None:
        return None
    val = parent.get(key)
    return val if isinstance(val, tomlkit.items.AbstractTable) else None


def get_array(
    parent: tomlkit.items.AbstractTable | tomlkit.container.Container | None,
    key: str,
) -> tomlkit.items.Array | None:
    """Return the tomlkit sub-array ``parent[key]``, or ``None``.

    tomlkit's ``__getitem__`` is typed as the loose ``Item | Container``
    union; this helper narrows it to an array for callers that rely on
    list-like access.
    """
    if parent is None:
        return None
    val = parent.get(key)
    return val if isinstance(val, tomlkit.items.Array) else None
