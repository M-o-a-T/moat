"""
This module contains various helper functions and classes for dictionaries.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy

from . import NotGiven

__all__ = ["combine_dict", "drop_dict", "attrdict", "to_attrdict"]


def combine_dict(*d, cls=dict, deep=False) -> dict:
    """
    Returns a dict with all keys+values of all dict arguments.
    The first found value wins.

    This operation is recursive and non-destructive. If `deep` is set, the
    result always is a deep copy.

    A value of `NotGiven` causes an entry to be skipped.

    TODO: arrays are not merged.

    Args:
      cls (type): a class to instantiate the result with. Default: dict.
        Often used: :class:`attrdict`.
      deep (bool): if set, always copy.
    """
    res = cls()
    keys = {}
    if not d:
        return res

    if len(d) == 1 and deep and not isinstance(d[0], Mapping):
        if deep and isinstance(d[0], (list, tuple)):
            return deepcopy(d[0])
        else:
            return d[0]

    for kv in d:
        if kv is None:
            continue
        for k, v in kv.items():
            if k not in keys:
                keys[k] = []
            keys[k].append(v)

    for k, v in keys.items():
        if v[0] is NotGiven:
            pass
        elif len(v) == 1 and not deep:
            res[k] = v[0]
        elif not isinstance(v[0], Mapping):
            for vv in v[1:]:
                assert vv is NotGiven or not isinstance(vv, Mapping)
            if deep and isinstance(v[0], (list, tuple)):
                res[k] = deepcopy(v[0])
            else:
                res[k] = v[0]
        else:
            res[k] = combine_dict(*v, cls=cls)

    return res


def drop_dict(data: Mapping, drop: tuple[str | tuple[str]]) -> Mapping:
    """
    Helper to remove some entries from a mapping hierarchy

    Returns a new mapping. The original is not changed.
    """
    data = data.copy()
    for d in drop:
        # ruff:noqa:PLW2901 # var overwritten
        vv = data
        if isinstance(d, (tuple, list)):
            for dd in d[:-1]:
                vv = vv[dd] = vv[dd].copy()
            d = d[-1]
        del vv[d]
    return data


class attrdict(dict):
    """
    A dictionary which can be accessed via attributes, for convenience.

    This also supports updating path accessors.
    """

    def __getattr__(self, a):
        if a.startswith("_"):
            return object.__getattribute__(self, a)
        try:
            return self[a]
        except KeyError:
            raise AttributeError(a) from None

    def __setattr__(self, a, b):
        if a.startswith("_"):
            super().__setattr__(a, b)
        else:
            self[a] = b

    def __delattr__(self, a):
        try:
            del self[a]
        except KeyError:
            raise AttributeError(a) from None

    def _get(self, path, skip_empty=True, default=NotGiven):
        """
        Get a node's value and access the dict items beneath it.
        """
        if isinstance(path, str):
            raise TypeError(f"Must be a Path/list, not {path!r}")
        val = self
        for p in path:
            if val is None:
                return None
            if skip_empty and not p:
                continue
            val = val.get(p, NotGiven)
            if val is NotGiven:
                if default is NotGiven:
                    raise KeyError(path)
                return default
        return val

    def _update(self, path, value=None, skip_empty=False):
        """
        Set some sub-item's value, possibly merging dicts.
        Items set to 'NotGiven' are deleted.

        Returns the new value. Modified (sub)dicts will be copied.
        """
        if isinstance(path, str):
            raise TypeError(f"Must be a Path/list, not {path!r}")
        if skip_empty:
            path = [p for p in path if p != ""]
        val = type(self)(**self)
        v = val
        if not path:
            if isinstance(value, Mapping):
                return combine_dict(value, val, cls=type(self))
            else:
                return value

        for p in path[:-1]:
            try:
                w = v[p]
            except KeyError:
                w = type(v)()
            else:
                # copy
                w = attrdict() if w is None else type(w)(w)
            v[p] = w
            v = w
        px = path[-1]
        if value is NotGiven:
            v.pop(px, None)
        elif isinstance(v, list) and px is None:
            v.append(value)
        elif not isinstance(value, Mapping):
            v[px] = value
        elif px in v:
            v[px] = combine_dict(value, v[px], cls=type(self))
        else:
            v[px] = value

        return val

    def _delete(self, path, skip_empty=True):
        """
        Remove some sub-item's value, possibly removing now-empty intermediate
        dicts.

        Returns the new value. Modified (sub)dicts will be copied.
        """
        if isinstance(path, str):
            raise TypeError(f"Must be a Path/list, not {path!r}")
        if skip_empty:
            path = [p for p in path if p]
        val = type(self)(**self)
        v = val
        vc = []
        for p in path[:-1]:
            vc.append(v)
            try:
                w = v[p]
            except KeyError:
                return self
            w = type(w)(**w)
            v[p] = w
            v = w
        vc.append(v)
        while path:
            v = vc.pop()
            v.pop(path.pop(), None)
            if v:
                break
        return val


def to_attrdict(d) -> attrdict:
    """
    Return a hierarchy with all dicts converted to attrdicts.
    """
    if isinstance(d, dict):
        return attrdict((k, to_attrdict(v)) for k, v in d.items())
    if isinstance(d, (tuple, list)):
        return [to_attrdict(v) for v in d]
    return d
