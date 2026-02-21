"""
Runtime helper for code snippets stored in MoaT-Link data.
"""

from __future__ import annotations

import anyio
import ast

from moat.util import NotGiven, combine_dict
from moat.lib.path import P, Path

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from types import CodeType

    from moat.link.client import LinkSender


class ReturnValue(BaseException):
    """
    Internal signal used to return values from compiled snippets.
    """

    value: Any

    def __init__(self, value: Any) -> None:
        super().__init__(value)
        self.value = value


class _ReturnRewriter(ast.NodeTransformer):
    """
    Rewrite module-level ``return`` statements to ``raise ReturnValue``.
    """

    _scope_level: int

    def __init__(self) -> None:
        super().__init__()
        self._scope_level = 0

    def _enter_scope(self, node: ast.AST) -> ast.AST:
        self._scope_level += 1
        try:
            return self.generic_visit(node)
        finally:
            self._scope_level -= 1

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:
        return self._enter_scope(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AST:
        return self._enter_scope(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> ast.AST:
        return self._enter_scope(node)

    def visit_Lambda(self, node: ast.Lambda) -> ast.AST:
        return self._enter_scope(node)

    def visit_Return(self, node: ast.Return) -> ast.AST:
        if self._scope_level:
            return self.generic_visit(node)
        value = node.value
        if value is None:
            value = ast.Constant(value=None)
        else:
            value = self.visit(value)
        ret = ast.Raise(
            exc=ast.Call(
                func=ast.Name(id="ReturnValue", ctx=ast.Load()),
                args=[value],
                keywords=[],
            ),
            cause=None,
        )
        return ast.copy_location(ret, node)


def make_proc(code: str, path: Any, *, use_async: bool = False) -> CodeType:
    """
    Compile snippet code directly for eval/await execution.
    """
    flags = ast.PyCF_ALLOW_TOP_LEVEL_AWAIT if use_async else 0
    tree = compile(code, str(path), "exec", flags=flags | ast.PyCF_ONLY_AST)
    tree = _ReturnRewriter().visit(tree)
    ast.fix_missing_locations(tree)
    return compile(tree, str(path), "exec", flags=flags)


class Code:
    """
    Call wrapper for code snippets stored under ``code.exec``.

    The snippets are loaded from ``path`` and compiled lazily. This object
    transparently handles async code, direct sync code, and thread-offloaded
    sync code.
    """

    link: LinkSender
    path: Path

    _proc: CodeType | None = None
    _is_async: bool | None = None
    _vars: dict[str, Any] = {}
    _data: Mapping[str, Any] | Any = NotGiven

    def __init__(self, link: LinkSender, path: Path):
        self.link = link
        self.path = Path.build(path)

    def _load(self, data: Mapping[str, Any]) -> None:
        """Compile code data if no compiled process is cached."""
        if self._proc is not None:
            return
        if not isinstance(data, Mapping):
            raise TypeError(f"{self.path}: record must be a mapping")

        code = data["code"]
        is_async = data.get("is_async", None)
        self._proc = make_proc(code, self.path / "code", use_async=is_async is True)
        self._is_async = is_async

    def update(self, new_data: Mapping[str, Any], compile: bool = False) -> None:  # noqa: A002
        """
        Replace stored record data and optionally compile it immediately.
        """
        self._data = new_data
        self._proc = None
        self._is_async = None
        if compile:
            self._load(new_data)

    def _globals(self, kw: dict[str, Any]) -> dict[str, Any]:
        """
        Build default globals exposed to snippet code.
        """
        return dict(
            runner=self,
            link=self.link,
            path=self.path,
            args=(),
            kw=kw,
            anyio=anyio,
            P=P,
            Path=Path,
            NotGiven=NotGiven,
            ReturnValue=ReturnValue,
        )

    @staticmethod
    def _exec(proc: CodeType, vars_: dict[str, Any]) -> Any:
        """Execute one compiled snippet with explicit locals."""
        return eval(proc, locals=vars_)

    async def __call__(self, **kw: Any) -> Any:
        """
        Execute the snippet and return its result.
        """
        if self._proc is None:
            if self._data is NotGiven:
                self._data = await self.link.d_get(self.path)
            self._load(self._data)
        assert self._proc is not None  # set by _load

        call_kw = combine_dict(kw, self._data.get("vars", {}), self._globals(kw))

        if self._is_async is False:
            try:
                await anyio.to_thread.run_sync(self._exec, self._proc, call_kw)
            except ReturnValue as exc:
                return exc.value
            return None

        try:
            res = self._exec(self._proc, call_kw)
            if self._is_async is True:
                await res
        except ReturnValue as exc:
            return exc.value
        return None
