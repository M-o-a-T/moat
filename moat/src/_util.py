"""
A couple of helper functions
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from moat.lib.path import P

    from collections.abc import Callable


def dash(n: str) -> str:
    """
    moat.foo.bar > moat-foo-bar
    foo.bar > foo-bar
    """
    return n.replace(".", "-")


def under(n: str) -> str:
    """
    moat.foo.bar > moat_foo_bar
    foo.bar > foo_bar
    """
    return n.replace(".", "_")


def undash(n: str) -> str:
    """
    moat-foo-bar > moat.foo.bar
    foo-bar > foo.bar
    """
    return n.replace("-", ".")


def _mangle(proj: Any, path: P, mangler: Callable[[Any], Any]) -> None:
    """Apply *mangler* to the value at *proj[path]*."""
    try:
        for k in path[:-1]:
            proj = proj[k]
        k = path[-1]
        v = proj[k]
    except KeyError:
        return
    v = mangler(v)
    proj[k] = v


def decomma(proj: Any, path: P) -> None:
    """comma-delimited string > list"""
    _mangle(proj, path, lambda x: x.split(","))


def encomma(proj: Any, path: P) -> None:
    """list > comma-delimited string"""
    _mangle(proj, path, lambda x: ",".join(x))  # noqa:PLW0108


class Replace:
    """Encapsulates a series of string replacements."""

    def __init__(self, **kw: str) -> None:
        self.changes: dict[str, str] = kw

    def __call__(self, s: str) -> str:
        if isinstance(s, str):
            for k, v in self.changes.items():
                s = s.replace(k, v)
        return s
