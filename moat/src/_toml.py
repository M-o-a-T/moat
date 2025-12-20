"""
Get tomlkit and teach yaml about its classes.
"""

from __future__ import annotations

import tomlkit

from moat.util import add_repr

__all__ = ["tomlkit"]

add_repr(tomlkit.items.String)
add_repr(tomlkit.items.Integer)
add_repr(tomlkit.items.Bool, bool)
add_repr(tomlkit.items.AbstractTable)
add_repr(tomlkit.items.Array)
