"""
Runtime helper for code snippets stored in MoaT-Link data.
"""

from __future__ import annotations

import anyio
from functools import partial

from moat.util import NotGiven
from moat.lib.path import P, Path
from moat.util.module import make_proc

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from moat.link.client import LinkSender

    from collections.abc import Callable


CODE_EXEC_PATH = P("code.exec")
CODE_IS_ASYNC_PATH = P("code.is_async")
CODE_VARS_PATH = P("code.vars")


def _get_sub(data: Mapping[str, Any], path: Path, default: Any = NotGiven) -> Any:
    """Read a nested subpath from a mapping."""
    cur: Mapping[str, Any] | Any = data
    for part in path:
        if not isinstance(cur, Mapping):
            if default is NotGiven:
                raise KeyError(path)
            return default
        cur = cur.get(part, NotGiven)
        if cur is NotGiven:
            if default is NotGiven:
                raise KeyError(path)
            return default
    return cur


def _sanitize_vars(value: Any) -> tuple[str, ...]:
    """Normalize the configured argument names."""
    if value in (NotGiven, None):
        return ()
    if not isinstance(value, list | tuple):
        raise TypeError("code.vars must be a list")
    return tuple(str(v) for v in value)


def _sanitize_async_mode(value: Any) -> bool | None:
    """Normalize the configured async mode."""
    if value in (NotGiven, None, True, False):
        return None if value in (NotGiven, None) else value
    raise TypeError("code.is_async must be true, false, or null")


class Runner:
    """
    Call wrapper for ``code.exec`` snippets at a data path.

    The snippets are loaded from ``path`` and compiled lazily. This object
    transparently handles async code, direct sync code, and thread-offloaded
    sync code.
    """

    link: LinkSender
    path: Path

    _signature: tuple[str, tuple[str, ...], bool | None] | None = None
    _proc: Callable[..., Any] | None = None
    _is_async: bool | None = None

    def __init__(self, link: LinkSender, path: Path):
        self.link = link
        self.path = Path.build(path)

    async def _load(self) -> None:
        """Load and compile the current code entry, if needed."""
        data = await self.link.d_get(self.path)
        if not isinstance(data, Mapping):
            raise TypeError(f"{self.path}: record must be a mapping")

        code = _get_sub(data, CODE_EXEC_PATH, NotGiven)
        if code is NotGiven:
            raise KeyError(self.path + CODE_EXEC_PATH)
        if not isinstance(code, str):
            raise TypeError(f"{self.path}: code.exec must be a string")

        vars_ = _sanitize_vars(_get_sub(data, CODE_VARS_PATH, ()))
        is_async = _sanitize_async_mode(_get_sub(data, CODE_IS_ASYNC_PATH, None))
        sig = (code, vars_, is_async)
        if sig == self._signature:
            return

        self._proc = make_proc(code, vars_, self.path + CODE_EXEC_PATH, use_async=is_async is True)
        self._is_async = is_async
        self._signature = sig

    def _globals(self, args: tuple[Any, ...], kw: dict[str, Any]) -> dict[str, Any]:
        """
        Build default globals exposed to snippet code.
        """
        return dict(
            runner=self,
            link=self.link,
            path=self.path,
            args=args,
            kw=kw,
            anyio=anyio,
            P=P,
            Path=Path,
            NotGiven=NotGiven,
        )

    async def __call__(self, *args: Any, **kw: Any) -> Any:
        """
        Execute the snippet and return its result.
        """
        await self._load()
        assert self._proc is not None  # set by _load

        glb = self._globals(args, kw)
        call_kw = dict(kw)
        for key, value in glb.items():
            call_kw.setdefault(key, value)

        if self._is_async is False:
            proc = self._proc
            if call_kw:
                proc = partial(proc, **call_kw)
            return await anyio.to_thread.run_sync(proc, *args)

        res = self._proc(*args, **call_kw)
        if self._is_async is True:
            return await res
        return res
