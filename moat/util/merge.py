"Support for merge-in-place of dict contents"

from __future__ import annotations

__all__ = ["merge"]


from .impl import NotGiven


def _merge_dict(d, other, drop=False, replace=True):
    for key, value in other.items():
        if value is NotGiven:
            d.pop(key, None)
        elif key in d:
            d[key] = _merge_one(d[key], value, drop=drop, replace=replace)
        else:
            d[key] = value

    if drop:
        keys = []
        for k in d.keys():  # noqa:SIM118
            if k not in other:
                keys.append(k)
        for k in keys:
            del d[k]


def _merge_list(item, value, drop=False, replace=True):
    off = 0
    if isinstance(value, (list, tuple)):
        # two lists
        lim = len(item)
        for i in range(min(lim, len(value))):
            if value[i] is NotGiven:
                item.pop(i - off)
                off += 1
            else:
                item[i - off] = _merge_one(item[i - off], value[i], drop=drop, replace=replace)

        while len(item) + off < len(value):
            val = value[len(item) + off]
            if val is NotGiven:
                off += 1
            else:
                item.append(val)

        if drop:
            while len(item) + off > len(value):
                item.pop()

    else:
        # a list, and a dict with updated/new/deleted values
        for i in range(len(item)):
            if i in value:
                val = value[i]
                if val is NotGiven:
                    item.pop(i - off)
                    off += 1
                else:
                    item[i - off] = _merge_one(item[i - off], val, drop=drop, replace=replace)

        while len(item) + off in value:
            val = value[len(item) + off]
            if val is NotGiven:
                off += 1
            else:
                item.append(val)


def _merge_one(d, other, drop=False, replace=True):
    if isinstance(d, dict):
        if isinstance(other, dict):
            _merge_dict(d, other, drop=drop, replace=replace)
        else:
            return other if replace else d
    elif isinstance(d, list):
        if isinstance(other, (dict, list, tuple)):
            _merge_list(d, other, drop=drop, replace=replace)
        else:
            return other if replace else d
    else:
        if replace:
            return d if other is None else other
        else:
            return other if d is None else d
    return d


def merge(d, *others, drop=False, replace=True):
    """
    Deep-merge a "source" and one or more "replacement" data structures.

    In contrast to `combine_dict`, the source is modified in-place.

    Rules:
    * two dicts: recurse into same-key items, and adds new items
    * two lists: recurse into same-index items
      append to the source if the replacement is longer
    * a list and a dict treats the dict as a sparse list. The value of numeric keys just
      beyond the list's length are appended, others are ignored.
    * a replacement value of `NotGiven` deletes the source entry
    * otherwise, use the second argument if it is not None, otherwise the first
      * except that if "replace" is False, these are swapped

    If "drop" is given, delete source keys that are not in the destination.
    This is useful for in-place replacements.
    """
    for other in others:
        d = _merge_one(d, other, drop=drop, replace=replace)
    return d
