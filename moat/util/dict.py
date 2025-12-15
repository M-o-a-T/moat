"""
This module contains various helper functions and classes for dictionaries.
"""

from __future__ import annotations

from copy import deepcopy
from weakref import ref

from . import NotGiven
from .merge import merge
from .path import Path

from collections.abc import Mapping
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any

__all__ = ["attrdict", "combine_dict", "drop_dict", "to_attrdict"]


def combine_dict(*d, cls=dict, deep=False, replace: bool = False) -> dict:
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
      replace: whether the first (default, False) or last (True) entry wins
    """
    res = cls()
    if not d:
        return res

    keys = {}
    idx = -1 if replace else 0
    post = False if issubclass(cls, attrdict) else None

    if len(d) == 1 and deep and not isinstance(d[0], Mapping):
        if deep and isinstance(d[0], (list, tuple)):
            return deepcopy(d[0])
        else:
            return d[0]

    for kv in d:
        if post is False and getattr(d, "_post", False):
            post = True
        if kv is None:
            continue
        if not isinstance(kv, dict):
            raise TypeError
        for k, v in kv.items():
            if k not in keys:
                keys[k] = []
            keys[k].append(v)

    for k, v in keys.items():
        for i, vv in enumerate(v):
            if isinstance(vv, Path) and vv.is_relative:
                v[i] = d[idx].root_.get_(vv)
        if v[idx] is NotGiven:
            pass
        elif len(v) == 1 and not deep:
            res[k] = v[0]
        elif not isinstance(v[idx], Mapping):
            for vv in v[:-1] if replace else v[1:]:
                assert not isinstance(vv, Mapping)
            if deep and isinstance(v[idx], (list, tuple)):
                res[k] = deepcopy(v[idx])
            else:
                res[k] = v[idx]
        else:
            res[k] = combine_dict(*v, cls=cls, replace=replace)

    if post:
        res.set_post_()
    return res


def drop_dict(data: Mapping, drop: tuple[str | tuple[str]]) -> Mapping:
    """
    Helper to remove some entries from a mapping hierarchy

    Returns a new mapping. The original is not changed.
    """
    data = data.copy()
    if getattr(data, "needs_post_", False):
        data.set_post_()
    for d in drop:
        # ruff:noqa:PLW2901 # var overwritten
        vv = data
        if isinstance(d, (tuple, list)):
            for dd in d[:-1]:
                vn = vv[dd].copy()
                if getattr(vv[dd], "needs_post_", False):
                    vn.set_post_()
                vv = vv[dd] = vn
            d = d[-1]
        del vv[d]
    return data


def _check_post(a, b) -> bool:
    if isinstance(a, str):
        if a[0] == "$":
            return True
    if isinstance(b, Path) and b.is_relative:
        return True
    if isinstance(b, list):
        for x in b:
            if _check_post(None, x):  # don't need the index here
                return True
    if getattr(b, "needs_post_", False):
        return True
    return False


class attrdict(dict):
    """
    A dictionary which can be accessed via attributes, for convenience.

    This also supports updating path accessors.
    """

    _post: bool = False
    _super = None

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        for a, b in self.items():
            if _check_post(a, b):
                self._post = True
                return

    @property
    def root_(self):
        "Follow the _super chain"
        s = self
        while True:
            try:
                if (sp := s._super) is None:  # noqa:SLF001
                    return s
            except AttributeError:
                return s
            else:
                s = sp()

    def __getattr__(self, a):
        if a.startswith("_"):
            return object.__getattribute__(self, a)
        try:
            return self[a]
        except KeyError:
            raise AttributeError(a) from None

    def __setitem__(self, a, b):
        if not self._post and _check_post(a, b):
            self._post = True
        if isinstance(b, attrdict):
            b._super = ref(self)  # noqa:SLF001
        super().__setitem__(a, b)

        if not self._post:
            return

        s = self
        while True:
            if not s._super:  # noqa:SLF001
                return
            if not (sup := s._super()):  # noqa:SLF001
                return
            if sup._post:  # noqa:SLF001
                return
            s = sup
            s._post = True  # noqa:SLF001

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

    @property
    def needs_post_(self):
        """
        Returns a flag whether this attrdict requires postprocessing.
        """
        return self._post

    def set_post_(self):
        """
        Set the flag signalling that this attrdict requires postprocessing.
        """
        self._post = True

    def get_(self, path, default=NotGiven):
        """
        Get a node's value and access the dict items beneath it.
        """
        if isinstance(path, str):
            raise TypeError(f"Must be a Path/list, not {path!r}")
        val = self
        for p in path:
            if val is None:
                return None
            val = val.get(p, NotGiven)
            if val is NotGiven:
                if default is NotGiven:
                    raise KeyError(path)
                return default
        return val

    _get = get_

    def setdefault(self, a, b):
        """
        Standard dict setdefault but updates _post
        """
        if a in self:
            return self[a]
        self[a] = b
        return b

    def update(self, a=None, **kw):
        """
        Standard dict update but updates _post
        """
        if a is None:
            pass
        elif hasattr(a, "items"):
            for k, v in a.items():
                self[k] = v
        else:
            for k, v in a:
                self[k] = v
        for k, v in kw.items():
            self[k] = v

    def update_(self, path, value=None):
        """
        Set some sub-item's value, possibly merging dicts.
        Items set to 'NotGiven' are deleted.

        Returns the new value. Modified (sub)dicts will be copied.
        """
        if isinstance(path, str):
            raise TypeError(f"Must be a Path/list, not {path!r}")
        val = type(self)()
        val.update(self)
        if getattr(self, "needs_post_", False):
            val.set_post_()

        if not path:
            if isinstance(value, Mapping):
                return combine_dict(value, val, cls=type(self))
            else:
                return value

        px = path[-1]
        post = _check_post(px, value)

        v = val
        if post and isinstance(v, attrdict):
            v.set_post_()
        for p in path[:-1]:
            try:
                w = v[p]
            except KeyError:
                w = type(v)()
            except TypeError:
                if isinstance(v, list) and p is None:
                    p = len(v)
                    v.append(None)
                    w = attrdict()
                else:
                    raise
            else:
                # copy
                wx = attrdict() if w is None else type(w)(w)
                if getattr(w, "needs_post_", False):
                    wx.set_post_()
                w = wx
            v[p] = w
            v = w
            if post and isinstance(v, attrdict):
                v.set_post_()

        if value is NotGiven:
            v.pop(px, None)
        elif isinstance(v, list):
            if px is None:
                v.append(value)
                return val
            if px >= len(v):
                if px > len(v) + 10:
                    raise ValueError(f"Won't pad the array (want {px}, has {len(v)}).")
                v.extend([NotGiven] * (1 + px - len(v)))
            v[px] = value
        elif not isinstance(v, Mapping):
            raise ValueError((v, px))
        elif px in v and isinstance(v[px], Mapping):
            v[px] = value = combine_dict(value, v[px], cls=type(self))
        else:
            v[px] = value

        return val

    _update = update_

    def set_(self, path: Path, value: Any, apply_notgiven=True) -> attrdict:
        """
        Set some sub-item's value, possibly merging dicts.
        No copying; deleting an entry when the value is NotGiven is optional.

        This function returns Self, *except* when the input path is empty
        and the value is not a Mapping. The latter case is not typed.
        """
        if isinstance(path, str):
            raise TypeError(f"Must be a Path/list, not {path!r}")

        if not path:
            if isinstance(value, Mapping):
                return merge(self, value, replace=True)
            else:
                return value

        px = path[-1]
        post = _check_post(px, value)
        v = self

        if post and isinstance(v, attrdict):
            v.set_post_()
        for p in path[:-1]:
            try:
                w = v[p]
            except KeyError:
                w = type(v)()
            except TypeError:
                if isinstance(v, list) and p is None:
                    p = len(v)
                    v.append(None)
                    w = attrdict()
                else:
                    raise
            else:
                # create/copy
                if w is None:
                    w = type(v)()
            v[p] = w
            v = w
            if post and isinstance(v, attrdict):
                v.set_post_()

        if apply_notgiven and value is NotGiven:
            v.pop(px, None)
        elif isinstance(v, list):
            if px is None:
                v.append(value)
                return self
            if px >= len(v):
                if px > len(v) + 10:
                    raise ValueError(f"Won't pad the array (want {px}, has {len(v)}).")
                v.extend([NotGiven] * (1 + px - len(v)))
            v[px] = value
        elif not isinstance(v, Mapping):
            raise ValueError((v, px))
        elif px in v and isinstance(v[px], Mapping):
            merge(v[px], value, replace=True)
        else:
            v[px] = value

        return self

    def delete_(self, path):
        """
        Remove some sub-item's value, possibly removing now-empty intermediate
        dicts.

        Returns the new value. Modified (sub)dicts will be copied.
        """
        if isinstance(path, str):
            raise TypeError(f"Must be a Path/list, not {path!r}")
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

    _delete = delete_


def to_attrdict(d) -> attrdict:
    """
    Return a hierarchy with all dicts converted to attrdicts.
    """
    if isinstance(d, dict):
        return attrdict((k, to_attrdict(v)) for k, v in d.items())
    if isinstance(d, (tuple, list)):
        return [to_attrdict(v) for v in d]
    return d
