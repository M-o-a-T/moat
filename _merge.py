__all__ = ["merge"]


from . import NotGiven


def _merge_dict(d, other):
    for key, value in other.items():
        if value is NotGiven:
            d.pop(key, None)
        elif key in d:
            d[key] = _merge_one(d[key], value)
        else:
            d[key] = value


def _merge_list(item, value):
    off=0
    if isinstance(value,(list,tuple)):
        # two lists
        lim = len(item)
        for i in range(min(lim,len(value))):
            if value[i] is NotGiven:
                item.pop(i-off)
                off += 1
            else:
                item[i-off] = _merge_one(item[i-off], value[i])

        while len(item)+off < len(value):
            val = value[len(item)+off]
            if val is NotGiven:
                off += 1
            else:
                item.append(val)

    else:
        # a list, and a dict with updated/new/deleted values
        for i in range(len(item)):
            if i in value:
                val = value[i]
                if val is NotGiven:
                    item.pop(i-off)
                    off += 1
                else:
                    item[i-off] = _merge_one(item[i-off], val)

        while len(item)+off in value:
            val = value[len(item)+off]
            if val is NotGiven:
                off += 1
            else:
                item.append(val)


def _merge_one(d, other):
    if isinstance(d, dict):
        if isinstance(other, dict):
            _merge_dict(d, other)
        else:
            return other
    elif isinstance(d, list):
        if isinstance(other, (dict,list,tuple)):
            _merge_list(d, other)
        else:
            return other
    else:
        return d if other is None else other
    return d


def merge(d, *others):
    """
    Deep-merge two data structures. Values from later structures overwrite earlier ones.
    Values of `NotGiven` are deleted.

    Rules:
    * Two dicts recurses into same-key items, and adds new items
    * Two lists recurses into same-index items, and appends from a longer list
    * A list and a dict treats the dict as a sparse list. The value of numeric keys just
      beyond the list's length are appended, others are ignored.
    * otherwise, returns the second argument if it is not None, otherwise the first

    This applies recursively.
    """
    for other in others:
        d = _merge_one(d,other)
    return d

