"""
Helpers for MoaT command interpreters et al.
"""

from __future__ import annotations

from moat.util import NotGiven

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence
    from typing import Any


def get_part(cur: Any, p: Sequence[str | int], add: bool = False) -> Any:
    """Walk into a mapping or object structure."""
    for pp in p:
        try:
            cur = getattr(cur, pp)  # type: ignore[arg-type]  # pp might be int but then getattr raises
        except (TypeError, AttributeError):
            try:
                cur = cur[pp]
            except TypeError:
                if pp is None:
                    raise KeyError(p, pp) from None
                raise
            except KeyError:
                if not add:
                    raise KeyError(p, pp) from None
                cur[pp] = nc = []
                cur = nc
    return cur


def set_part(cur: Any, p: Sequence[str | int], v: Any, keep: bool = False) -> None:
    """Modify a mapping or object structure."""
    cur = get_part(cur, p[:-1], add=True)
    pp = p[-1]

    if v is NotGiven and not keep:
        try:
            cur.pop(pp, None)
        except (TypeError, AttributeError):
            if pp is None or (isinstance(pp, int) and len(cur) == pp):
                cur.pop()
            else:
                cur.remove(pp)

    else:
        try:
            cur[pp] = v
        except (TypeError, AttributeError):
            if pp is None or (isinstance(pp, int) and len(cur) == pp):
                cur.append(v)
            else:
                setattr(cur, pp, v)  # type: ignore[arg-type]  # pp might be int but then we append above


def enc_part(
    cur: Any, name: str | None = None
) -> tuple[Any, tuple[Any, ...] | None] | tuple[Any, Sequence[int | str]] | Any:
    """
    Helper method to encode a larger dict/list partially.

    The result is either some object that's not a dict or list, or a
    (X,L) tuple where X is the dict/list in question except with all the
    complex parts removed, and L is a list of keys/offsets with complex
    data to retrieve

    The tuple may have a third element: the name, if passed in.
    """

    def _complex(v: Any) -> bool:
        if isinstance(v, dict | list | tuple):
            return True
        return False

    if isinstance(cur, dict):
        c: dict[Any, Any] = {}
        s: list[str | int] = []
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

    elif isinstance(cur, list | tuple):
        c_list: list[Any] = []
        s_list: list[int] = []
        for k, v in enumerate(cur):
            if _complex(v):
                c_list.append(None)
                s_list.append(k)
            else:
                c_list.append(v)
        # cannot do a direct return here
        return c_list, s_list

    else:
        return cur
        # guaranteed not to be a tuple
