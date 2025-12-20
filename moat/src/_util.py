"""
A couple of helper functions
"""

from __future__ import annotations


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


def _mangle(proj, path, mangler):
    try:
        for k in path[:-1]:
            proj = proj[k]
        k = path[-1]
        v = proj[k]
    except KeyError:
        return
    v = mangler(v)
    proj[k] = v


def decomma(proj, path):
    """comma-delimited string > list"""
    _mangle(proj, path, lambda x: x.split(","))


def encomma(proj, path):
    """list > comma-delimited string"""
    _mangle(proj, path, lambda x: ",".join(x))  # pylint: disable=unnecessary-lambda


class Replace:
    """Encapsulates a series of string replacements."""

    def __init__(self, **kw):
        self.changes = kw

    def __call__(self, s):
        if isinstance(s, str):
            for k, v in self.changes.items():
                s = s.replace(k, v)
        return s
