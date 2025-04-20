"""
Data access
"""

from __future__ import annotations

import datetime
import os
import sys
import time
from collections.abc import Mapping

from .node import Node
from .meta import MsgMeta
from moat.util import NotGiven, Path, attrdict, process_args, yprint, PathLongener
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
    obj,
    path,
    *,
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

    if recursive:
        kw = {}
        if maxdepth is not None and maxdepth >= 0:
            kw["max_depth"] = maxdepth
        if mindepth:
            kw["min_depth"] = mindepth
        if empty:
            kw["empty"] = True
        y = {}
        pl=PathLongener()
        async with obj.conn.d.walk(path, **kw).stream_in() as res:
            async for r in res:
                r = await item_mangle(r)
                if r is None:
                    continue
                n,p,d,*m = r
                path=pl.long(n,p)
                path = path_mangle(path)
                if path is None:
                    continue
                if obj.meta:
                    m=MsgMeta._moat__restore(m, NotGiven)
                    d = dict(data=d,meta=m.repr())

                if as_dict is not None:
                    yy = y
                    for p in path:
                        yy = yy.setdefault(p, {})
                    try:
                        yy[as_dict] = d
                    except AttributeError:
                        if empty:
                            yy[as_dict] = None
                else:
                    if raw:
                        y = path
                    else:
                        y = {}
                        try:
                            y[path] = d
                        except AttributeError:
                            if empty:
                                y[path] = None
                            else:
                                continue
                    yprint([y], stream=obj.stdout)

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
                yprint(y, stream=obj.stdout)
            return  # end "if recursive"

    
    d,*m = await obj.conn.d.get(path)
    if obj.meta:
        m=MsgMeta.restore(m)
        d=dict(data=d,meta=m.repr())

    if not raw:
        yprint(d, stream=obj.stdout)
    elif isinstance(d, bytes):
        os.write(obj.stdout.fileno(), res)
    else:
        obj.stdout.write(str(d))
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


async def node_attr(obj, path, val=NotGiven, meta=NotGiven, **kw):
    """
    Sub-attr setter.

    Args:
        obj: command object
        path: address of the node to change
        res: old node, if it has been read already
        **kw: the results of `attr_args`

    Returns the result of setting the attribute.
    """
    if val is NotGiven:
        try:
            val,*m = await obj.conn.d.get(path)
        except KeyError:
            pass
        else:
            meta = MsgMeta.restore(m)
    val = process_args(val, **kw)
    t = {} if meta is NotGiven else {'t':meta.timestamp}
    if val is NotGiven:
        res = await obj.conn.d.delete(path, **t)
    else:
        res = await obj.conn.d.set(path, val, **t)
    res = res[0],MsgMeta.restore(res[1:])
    return res
