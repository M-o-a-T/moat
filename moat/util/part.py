"""
Helpers for MoaT command interpreters et al.
"""

from __future__ import annotations

# Typing

from typing import TYPE_CHECKING  # isort:skip

if TYPE_CHECKING:
    from typing import Any


def get_part(cur, p: list[str | int], add: bool = False):
    "Walk into a mapping or object structure"
    for pp in p:
        try:
            cur = getattr(cur, pp)
        except (TypeError, AttributeError):
            try:
                cur = cur[pp]
            except KeyError:
                if not add:
                    raise KeyError(p, pp) from None
                cur[pp] = nc = []
                cur = nc
    return cur


def set_part(cur, p: list[str | int], v: Any):
    "Modify a mapping or object structure"
    cur = get_part(cur, p[:-1], add=True)
    try:
        cur[p[-1]] = v
    except TypeError:
        setattr(cur, p[-1], v)


def enc_part(cur, name=None) -> tuple[Any, tuple | None] | Any:
    """
    Helper method to encode a larger dict/list partially.

    The result is either some object that's not a dict or list, or a
    (X,L) tuple where X is the dict/list in question except with all the
    complex parts removed, and L is a list of keys/offsets with complex
    data to retrieve

    The tuple may have a third element: the name, if passed in.
    """

    def _complex(v):
        if isinstance(v, (dict, list, tuple)):
            return True
        return False

    if isinstance(cur, dict):
        c = {}
        s = []
        for k, v in cur.items():
            if _complex(v):
                s.append(k)
            else:
                c[k] = v
        if s or name:
            return (c, s, name) if name else (c, s)
        else:
            # dict has no complex values: return directly
            return c

    elif isinstance(cur, (list, tuple)):
        c = []
        s = []
        for k, v in enumerate(cur):
            if _complex(v):
                c.append(None)
                s.append(k)
            else:
                c.append(v)
        # cannot do a direct return here
        return c, s

    else:
        return cur
        # guaranteed not to be a tuple
