"""
Data access
"""

from __future__ import annotations

import anyio
import os
import sys
import time

from moat.util import NotGiven, attrdict, yprint
from moat.lib.path import Path, PathLongener
from moat.lib.run import process_args
from moat.util.times import ts2iso

from .meta import MsgMeta

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Literal, TextIO

if TYPE_CHECKING:
    from types import EllipsisType

    from moat.lib.codec import Codec
    from moat.link.client import Link

    from collections.abc import Awaitable, Callable


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
    conn: Link,
    path: Path,
    *,
    meta: bool = False,
    recursive: bool = True,
    as_dict: str | None = "_",
    maxdepth: int = -1,
    mindepth: int = 0,
    empty: bool = False,
    raw: bool = False,
    path_mangle: Callable[[Path], Path | None] | None = None,
    item_mangle: Callable[[Any], Awaitable[Any | None]] | None = None,
    add_date: bool = False,
    out: TextIO | Literal[False] | None = None,
):
    """Generic code to dump a subtree.

    `path_mangle` accepts a path and the as_dict parameter. It should
    return the new path. This is used for e.g. prefixing the path with a
    device name. Returning ``None`` causes the entry to be skipped.
    """
    if path_mangle is None:

        def path_mangle(x: Path) -> Path:
            return x

    if item_mangle is None:

        async def item_mangle(x: Any) -> Any:  # pylint: disable=function-redefined
            return x

    out_list: list[Any] | None = None
    out_stream: TextIO | None = None
    if out is None:
        out_stream = sys.stdout
    elif out is False:
        tmp: list[Any] = []
        out_list = tmp
    else:
        out_stream = out

    if recursive:
        kw: dict[str, Any] = {}
        a = [None, None, None]

        if maxdepth is not None and maxdepth >= 0:
            a[2] = maxdepth
        if mindepth:
            a[1] = mindepth
        if empty:
            kw["empty"] = True
        while a and a[-1] is None:
            a.pop()
        tree: dict[Any, Any] = {}
        pl = PathLongener()
        async with conn.d.walk(path, *a, **kw).stream_in() as res:
            async for r in res:
                r = await item_mangle(r)  # noqa:PLW2901
                if r is None:
                    continue
                n, p, d, *m_raw = r
                p = pl.long(n, p)
                row_path = path_mangle(p)
                if row_path is None:
                    continue

                if add_date:
                    add_dates(d)

                meta_data: dict[str, Any] | None = None
                if meta:
                    meta_obj: MsgMeta = MsgMeta._moat__restore(m_raw, NotGiven)  # noqa: SLF001
                    meta_data = meta_obj.repr()

                if as_dict is not None:
                    if meta:
                        d = dict(data=d, meta=meta_data, _path=p)
                    yy = tree
                    for p in row_path:
                        yy = yy.setdefault(p, {})
                    try:
                        yy[as_dict] = d
                    except AttributeError:
                        if empty:
                            yy[as_dict] = None
                else:
                    if raw:
                        msg: Any = row_path
                    elif meta:
                        msg = [row_path, d, meta_data]
                    else:
                        msg = [row_path, d]
                    if out_list is not None:
                        out_list.append(msg)
                    else:
                        assert out_stream is not None
                        yprint(msg, stream=out_stream)
                        out_stream.write("---\n")

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

                    tree = simplex(tree)

            if out_list is not None:
                return tree
            if as_dict is not None:
                assert out_stream is not None
                yprint(tree, stream=out_stream)

            return out_stream  # end "if recursive"

    d, *m = await conn.d.get(path)
    if add_date:
        add_dates(d)
    if meta:
        m = MsgMeta.restore(m)
        d = dict(data=d, meta=m.repr())

    if out is False:
        return d
    assert out_stream is not None
    if not raw:
        yprint(d, stream=out_stream)
    elif isinstance(d, bytes):
        os.write(out_stream.fileno(), d)
    else:
        out_stream.write(str(d))
    pass  # end get


async def backend_get(
    conn: Link,
    path: Path,
    *,
    meta: bool = False,
    recursive: bool = True,
    empty: bool = False,
    as_dict: str | None = "_",
    raw: bool = False,
    path_mangle: Callable[[Path], Path | None] | None = None,
    item_mangle: Callable[[Any], Awaitable[Any | None]] | None = None,
    add_date: bool = False,
    codec: Codec | None = None,
    out: TextIO | Literal[False] | None = None,
    timeout: float = 0.5,
):
    """Generic code to dump a backend subtree.

    `path_mangle` accepts a path and the as_dict parameter. It should
    return the new path. This is used for e.g. prefixing the path with a
    device name. Returning ``None`` causes the entry to be skipped.
    """
    # This is a copy of `data_get` that accesses the backend directly.

    if path_mangle is None:

        def path_mangle(x: Path) -> Path:
            return x

    if item_mangle is None:

        async def item_mangle(x: Any) -> Any:  # pylint: disable=function-redefined
            return x

    out_list: list[Any] | None = None
    out_stream: TextIO | None = None
    if out is None:
        out_stream = sys.stdout
    elif out is False:
        tmp: list[Any] = []
        out_list = tmp
    else:
        out_stream = out

    kw: dict[str, Any] = {"codec": codec}

    if recursive:
        tree: dict[Any, Any] = {}
        async with conn.monitor(path, subtree=True, **kw) as mon:
            while True:
                r = None
                with anyio.move_on_after(timeout):
                    r = await anext(mon)
                if r is None:
                    break

                r = await item_mangle(r)
                if r is None:
                    continue
                p, d, m = r.topic, r.data, r.meta
                p = p[len(path) :]
                p = path_mangle(p)
                if p is None:
                    continue

                if add_date:
                    add_dates(d)
                if meta:
                    m = MsgMeta._moat__restore(m, NotGiven)  # noqa: SLF001
                    d = dict(data=d, meta=m.repr())

                if as_dict is not None:
                    yy = tree
                    for pp in p:
                        yy = yy.setdefault(pp, {})
                    try:
                        yy[as_dict] = d
                    except AttributeError:
                        if empty:
                            yy[as_dict] = None
                else:
                    if raw:
                        msg: Any = p
                    else:
                        msg = {}
                        try:
                            msg[p] = d
                        except AttributeError:
                            if empty:
                                msg[p] = None
                            else:
                                continue
                    if out_list is not None:
                        out_list.append(msg)
                    else:
                        assert out_stream is not None
                        yprint([msg], stream=out_stream)

            if out_list is not None:
                return tree
            assert out_stream is not None
            yprint(tree, stream=out_stream)

            return out_stream  # end "if recursive"

    async with conn.monitor(path, **kw) as mon:
        r = None
        with anyio.move_on_after(timeout):
            r = await anext(mon)
        if r is None:
            raise KeyError(path)

    d, m = r.data, r.meta
    if add_date:
        add_dates(d)
    if meta:
        m = MsgMeta.restore(m)
        d = dict(data=d, meta=m.repr())

    if out is False:
        return d
    assert out_stream is not None
    if not raw:
        yprint(d, stream=out_stream)
    elif isinstance(d, bytes):
        os.write(out_stream.fileno(), d)
    else:
        out_stream.write(str(d))
    pass  # end get


def res_get(res, attr: Path, **kw):  # pylint: disable=redefined-outer-name
    """
    Get a node's value and access the dict items beneath it.

    The node value must be an attrdict.
    """
    val = res.get("value", None)
    if val is None:
        return None
    return val._get(attr, **kw)  # noqa: SLF001


def res_update(res, attr: Path, value=None, **kw):  # pylint: disable=redefined-outer-name
    """
    Set a node's sub-item's value, possibly merging dicts.
    Entries set to 'NotGiven' are deleted.

    The node value must be an attrdict.

    Returns the new value.
    """
    val = res.get("value", attrdict())
    return val._update(attr, value=value, **kw)  # noqa: SLF001


async def node_attr(
    obj,
    path,
    val: dict[str | None, Any] | EllipsisType = NotGiven,
    meta=NotGiven,
    *,
    retain: bool = False,
    **kw,
):
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
            val, *m = await obj.conn.d.get(path)
        except KeyError:
            pass
        else:
            meta = MsgMeta.restore(m)
    if val is None:
        val = {}
    val = process_args(None if val is NotGiven else val, **kw)
    if retain:
        t = {} if meta is NotGiven else {"t": meta.timestamp}
        if val is NotGiven:
            res = await obj.conn.d.delete(path, **t)
        else:
            res = await obj.conn.d.set(path, val, **t)
        meta = MsgMeta.restore(res[1:])
        res = res[0]
    else:
        if meta is NotGiven:
            meta = None
        meta = MsgMeta(name=obj.conn.name)
        res = val
        await obj.conn.d_set(path, val, meta)
    return res, meta
