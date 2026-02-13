"""
This module contains various helper functions and classes for dictionaries.
"""

from __future__ import annotations

from copy import deepcopy
from weakref import ref

from moat.lib.path import Path

from . import NotGiven
from ._merge import merge

from collections.abc import Hashable, Mapping, Sequence
from typing import TYPE_CHECKING, Any, TypeVar

if TYPE_CHECKING:
    from types import EllipsisType

    from collections.abc import Callable

__all__ = ["attrdict", "combine_dict", "to_attrdict"]

T = TypeVar("T", bound=dict)

_Nope = object()


def combine_dict(
    *d: Mapping[Hashable, Any] | EllipsisType,
    cls: type[dict] = dict,
    deep: bool = False,
    keep: bool = False,
) -> dict | EllipsisType:
    """
    Returns a dict with all keys+values of all dict arguments.
    The first found value wins.

    This operation is recursive and non-destructive. If ``deep`` is set, the
    result always is a deep copy.

    A value of `NotGiven` causes an entry to be skipped.

    TODO: arrays are not merged.

    Args:
        cls: a class to instantiate the result with. Default: dict.
             Often used: :class:`attrdict`.
        deep: if set, always copy.
        keep: whether to *not* delete `NotGiven` inputs.
    """
    res: dict = cls()
    if not d:
        return res
    if d[0] is NotGiven:
        return NotGiven if keep else res

    keys: dict[Hashable, list[Any]] = {}
    post: bool | None = False if issubclass(cls, attrdict) else None

    if len(d) == 1 and deep and not isinstance(d[0], Mapping):
        if deep and isinstance(d[0], list | tuple):
            return deepcopy(d[0])  # deepcopy returns Any
        else:
            return d[0]  # single non-mapping item

    for kv in d:
        if post is False and getattr(kv, "_post", False):
            post = True
        if kv is None:
            continue
        if kv is NotGiven:
            break
        if not isinstance(kv, dict):
            raise TypeError("All arguments must be dicts")
        for k, v in kv.items():
            if k not in keys:
                keys[k] = []
            keys[k].append(v)

    for k, v in keys.items():
        for i, vv in enumerate(v):
            if isinstance(vv, Path) and vv.is_relative:
                v[i] = d[0].root_.get_(vv)  # d[0] is checked to be attrdict-like
        if v[0] is NotGiven:
            if keep:
                res[k] = NotGiven  # NotGiven is allowed when keep=True
        elif len(v) == 1 and not deep:
            res[k] = v[0]
        elif not isinstance(v[0], Mapping):
            for vv in v[1:]:
                if isinstance(vv, Mapping):
                    raise ValueError(f"Merge {k!r}: {v!r}")  # noqa: TRY004  # ValueError is intentional
            if deep and isinstance(v[0], list | tuple):
                res[k] = deepcopy(v[0])
            else:
                res[k] = v[0]
        else:
            res[k] = combine_dict(*v, cls=cls, keep=keep)

    if post:
        try:
            res.set_post_()  # type: ignore[attr-defined]  # set_post_ exists on attrdict
        except AttributeError:
            pass
    return res


def _check_post(a: Hashable | None, b: Any) -> bool:
    if getattr(b, "_post", False):
        return True
    if isinstance(a, str) and a and a[0] == "$":
        return True
    if isinstance(b, Path):
        return b.is_relative
    if isinstance(b, str):
        return False
    if isinstance(b, Sequence):
        for x in b:
            if _check_post(None, x):  # don't need the index here
                return True
    return False


class attrdict(dict[Hashable, Any]):
    """
    A dictionary which can be accessed via attributes.

    Attributes with leading or trailing underscores are not stored.

    This class supports
    - updating via path accessors
    - recursively tagging updated parents
    """

    _post: bool = False
    _super: ref[attrdict] | None = None

    updated_: Callable[[attrdict], None] = lambda _: None
    "Callback. Used by moat.lib.config."

    def __init__(self, *a: Any, **kw: Any) -> None:
        super().__init__(*a, **kw)
        for a_key, b in self.items():
            if _check_post(a_key, b):
                self._post = True
                return

    @property
    def root_(self) -> attrdict:
        "Follow the _super chain"
        s: attrdict = self
        while True:
            try:
                if (sp := s._super) is None:
                    return s
            except AttributeError:
                return s
            else:
                s_ref = sp()
                if s_ref is None:
                    return s
                s = s_ref

    def __getattr__(self, a: str) -> Any:
        if a.startswith("_") or a.endswith("_"):
            return object.__getattribute__(self, a)
        try:
            return self[a]
        except KeyError:
            raise AttributeError(a) from None

    def __setitem__(self, a: Hashable, b: Any) -> None:
        if isinstance(b, attrdict):
            b._super = ref(self)  # noqa: SLF001  # accessing own class member
        if a not in self or _check_post(a, b) or self[a] != b:
            self._mark_post()
        super().__setitem__(a, b)

    def _mark_post(self) -> None:
        s: attrdict = self
        while True:
            if s._post:
                return
            s._post = True
            sup = s._super
            if not sup:
                return
            sup_ref = sup()
            if not sup_ref:
                return
            s = sup_ref

    def __setattr__(self, a: str, b: Any) -> None:
        if (a and a.startswith("_")) or a.endswith("_"):
            super().__setattr__(a, b)
        else:
            self[a] = b

    def __delattr__(self, a: str) -> None:
        if (a and a.startswith("_")) or a.endswith("_"):
            super().__delattr__(a)
        else:
            try:
                del self[a]
            except KeyError:
                raise AttributeError(a) from None

    def __delitem__(self, a: Hashable) -> None:
        super().__delitem__(a)
        self._mark_post()

    def pop(self, a: Hashable, default: Any = _Nope) -> Any:
        "remove and mark"
        try:
            res = super().pop(a)
        except KeyError:
            if default is _Nope:
                raise
            return default
        self._mark_post()
        return res

    @property
    def needs_post_(self) -> bool:
        """
        Returns a flag whether this attrdict requires postprocessing.

        Warning: Reading this attribute auto-clears the flag.
        """
        try:
            return self._post
        finally:
            self._post = False

    def set_post_(self) -> None:
        """
        Set the flag signalling that this attrdict requires postprocessing.
        """
        self._post = True

    def get_(self, path: Path, default: Any = NotGiven) -> Any:
        """
        Get a node's value and access the dict items beneath it.
        """
        if isinstance(path, str):
            raise TypeError(f"Must be a Path/list, not {path!r}")
        val: Any = self
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

    def setdefault(self, a: Hashable, b: Any = None) -> Any:
        """
        Standard dict setdefault but updates _post
        """
        if a in self:
            return self[a]
        if b is None:
            b = None
        self[a] = b
        return b

    def update(  # type: ignore[override]  # More flexible signature than dict.update
        self, a: Mapping[Hashable, Any] | Sequence[tuple[Hashable, Any]] | None = None, **kw: Any
    ) -> None:
        """
        Standard dict update but updates _post
        """
        if a is None:
            pass
        elif isinstance(a, Mapping):
            for k, v in a.items():
                self[k] = v
        else:
            for k, v in a:
                self[k] = v
        for k, v in kw.items():
            self[k] = v

    def update_(self, path: Path, value: Any = None) -> Any:
        """
        Set some sub-item's value, possibly merging dicts.
        Items set to 'NotGiven' are deleted.

        Returns the new value. Modified (sub)dicts will be copied.
        """
        if isinstance(path, str):
            raise TypeError(f"Must be a Path/list, not {path!r}")
        val = type(self)()
        val.update(self)
        if getattr(self, "_post", False):
            val.set_post_()

        if not path:
            if isinstance(value, Mapping):
                return combine_dict(value, val, cls=type(self))
            else:
                return value

        px = path[-1]
        post = _check_post(px, value)

        v: Any = val
        if post and isinstance(v, attrdict):
            v.set_post_()
        for p in path[:-1]:
            try:
                w = v[p]
            except KeyError:
                w = type(v)()
            except TypeError:
                if isinstance(v, list) and p is None:
                    p = len(v)  # noqa:PLW2901
                    v.append(None)
                    w = attrdict()
                else:
                    raise
            else:
                # copy
                wx = attrdict() if w is None else type(w)(w)
                if getattr(w, "_post", False):
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
            assert isinstance(px,int)
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

    def set_(self, path: Path, value: Any, apply_notgiven: bool = True) -> Any:
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
        v: Any = self

        if post and isinstance(v, attrdict):
            v.set_post_()
        for p in path[:-1]:
            try:
                w = v[p]
            except KeyError:
                w = type(v)()
            except TypeError:
                if isinstance(v, list) and p is None:
                    p = len(v)  # noqa:PLW2901
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

        if value is NotGiven:
            if apply_notgiven:
                v.pop(px, None)
            else:
                v[px] = NotGiven
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

    def delete_(self, path: Path) -> attrdict:
        """
        Remove some sub-item's value, possibly removing now-empty intermediate
        dicts.

        Returns the new value. Modified (sub)dicts will be copied.
        """
        if isinstance(path, str):
            raise TypeError(f"Must be a Path/list, not {path!r}")
        val = type(self)(self)
        path_list = list(path)
        v: Any = val
        vc: list[Any] = []
        for p in path_list[:-1]:
            vc.append(v)
            try:
                w = v[p]
            except KeyError:
                return self
            w = type(w)(w)
            v[p] = w
            v = w
        vc.append(v)
        while path_list:
            v = vc.pop()
            v.pop(path_list.pop(), None)
            if v:
                break
        return val

    _delete = delete_


def to_attrdict(d: Any) -> Any:
    """
    Return a hierarchy with all dicts converted to attrdicts.
    """
    if isinstance(d, dict):
        return attrdict((k, to_attrdict(v)) for k, v in d.items())
    if isinstance(d, tuple | list):
        return [to_attrdict(v) for v in d]
    return d
