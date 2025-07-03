"""
Data access
"""

from __future__ import annotations

import datetime
import os
import sys
import time
from collections.abc import Mapping

from moat.util import NotGiven, Path, attrdict, process_args, yprint
from moat.util.times import ts2iso
import contextlib


def add_dates(d):
    """
    Given a dict with int/float entries that might conceivably be dates,
    add ``_*`` with a textual representation.
    """

    t = time.time()
    start = t - 366 * 24 * 3600
    stop = t + 366 * 24 * 3600

    def _add(d):
        if isinstance(d, (list, tuple)):
            for dd in d:
                _add(dd)
            return
        if not isinstance(d, Mapping):
            return
        for k, v in list(d.items()):
            if isinstance(k, str) and k.startswith("_"):
                continue
            if not isinstance(v, (int, float)):
                _add(v)
                continue
            if start <= v <= stop:
                d[f"_{k}"] = ts2iso(v)

    _add(d)


async def data_get(
    conn,
    path,
    *,
    meta=False,
    recursive=True,
    as_dict="_",
    maxdepth=-1,
    mindepth=0,
    empty=False,
    raw=False,
    internal=False,
    path_mangle=None,
    item_mangle=None,
    add_date=False,
    out=None,
):
    """Generic code to dump a subtree.

    `path_mangle` accepts a path and the as_dict parameter. It should
    return the new path. This is used for e.g. prefixing the path with a
    device name. Returning ``None`` causes the entry to be skipped.
    """
    if path_mangle is None:

        def path_mangle(x):
            return x

    if item_mangle is None:

        async def item_mangle(x):  # pylint: disable=function-redefined
            return x

    if out is None:
        out = sys.stdout
    elif out is False:
        out = []

    if recursive:
        kw = {}
        if maxdepth is not None and maxdepth >= 0:
            kw["max_depth"] = maxdepth
        if mindepth:
            kw["min_depth"] = mindepth
        if empty:
            kw["empty"] = True
        if meta:
            kw.setdefault("nchain", meta)
        y = {}
        if internal:
            res = await conn._request(action="get_tree_internal", path=path, iter=True, **kw)
        else:
            res = conn.get_tree(path, **kw)
        async for r in res:
            r = await item_mangle(r)
            if r is None:
                continue
            r.pop("seq", None)
            path = r.pop("path")
            path = path_mangle(path)
            if path is None:
                continue
            if add_date and "value" in r:
                add_dates(r.value)

            if as_dict is not None:
                yy = y
                for p in path:
                    yy = yy.setdefault(p, {})
                try:
                    yy[as_dict] = r if meta else r.value
                except AttributeError:
                    if empty:
                        yy[as_dict] = None
            else:
                if raw:
                    y = path
                else:
                    y = {}
                    try:
                        y[path] = r if meta else r.value
                    except AttributeError:
                        if empty:
                            y[path] = None
                        else:
                            continue

                if isinstance(out,list):
                    out.append(y)
                else:
                    yprint([y], stream=out)

        if as_dict is not None:
            if maxdepth:

                def simplex(d):
                    for k, v in d.items():
                        if isinstance(v, dict):
                            d[k] = simplex(d[k])
                    if as_dict in d and d[as_dict] is None:
                        if len(d) == 1:
                            return None
                        else:
                            del d[as_dict]
                    return d

                y = simplex(y)
            if isinstance(out,list):
                return y
            yprint(y, stream=out)
        return  # end "if recursive"

    res = await conn.get(path, nchain=meta)
    if add_date and "value" in res:
        add_dates(res.value)
    if not meta:
        try:
            res = res.value
        except AttributeError:
#           if obj.debug:
#               print("No data at", path, file=sys.stderr)
            return

    if out is False:
        return d
    if not raw:
        yprint(res, stream=out)
    elif isinstance(res, bytes):
        os.write(out.fileno(), res)
    else:
        out.write(str(res))
    pass  # end get


def res_get(res, attr: Path, **kw):  # pylint: disable=redefined-outer-name
    """
    Get a node's value and access the dict items beneath it.

    The node value must be an attrdict.
    """
    val = res.get("value", None)
    if val is None:
        return None
    return val._get(attr, **kw)


def res_update(res, attr: Path, value=None, **kw):  # pylint: disable=redefined-outer-name
    """
    Set a node's sub-item's value, possibly merging dicts.
    Entries set to 'NotGiven' are deleted.

    The node value must be an attrdict.

    Returns the new value.
    """
    val = res.get("value", attrdict())
    return val._update(attr, value=value, **kw)


async def node_attr(obj, path, res=None, chain=None, **kw):
    """
    Sub-attr setter.

    Args:
        obj: command object
        path: address of the node to change
        res: old node, if it has been read already
        chain: change chain of node, copied from res if clear
        **kw: the results of `attr_args`

    Returns the result of setting the attribute.
    """
    if res is None:
        res = await obj.client.get(path, nchain=obj.meta or 2)
    if chain is None:
        with contextlib.suppress(AttributeError):
            chain = res.chain
    try:
        val = res.value
    except AttributeError:
        chain = None
        val = NotGiven
    val = process_args(val, **kw)
    if val is NotGiven:
        res = await obj.client.delete(path, nchain=obj.meta, chain=chain)
    else:
        res = await obj.client.set(path, value=val, nchain=obj.meta, chain=chain)
    return res
