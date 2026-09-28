"""
Test cases for stored code snippets.

A snippet at ``code.PATH`` keeps its test cases at ``code.PATH:n.CASE``:
the `None` element separates the snippet from its tests, as snippets can
have children of their own.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from moat.link.code import CODE_EXEC_ROOT

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from moat.lib.path import Path
    from moat.link.client import LinkSender

    from collections.abc import AsyncIterator

__all__ = ["ACTIONS", "CodeTest", "del_test", "get_test", "is_test_path", "list_tests", "set_test"]

ACTIONS: frozenset[str] = frozenset((
    "start",
    "set",
    "update",
    "delete",
    "send",
    "monitor",
    "wait",
    "check",
    "sleep",
    "result",
    "error",
    "comment",
))
"The verbs a test step may use."


class CodeTest(BaseModel):
    """
    One test case of a code snippet.

    Paths in `data`, `args` and `steps` are relative to the test root
    unless they start with ``:R``.
    """

    model_config = ConfigDict(extra="forbid")

    info: str | None = None
    "Short description."

    timeout: float = Field(default=30, gt=0)
    "Seconds for the whole test."

    data: dict[Any, Any] = Field(default_factory=dict)
    "Initial data below the test root, as ``moat link data … get -rd_`` shows it."

    args: dict[str, Any] = Field(default_factory=dict)
    "The job's ``data``, i.e. the snippet's parameters."

    steps: list[list[Any]] = Field(default_factory=list)
    "The actions, in order: ``[verb, arg, …]``."

    @field_validator("steps")
    @classmethod
    def _check_steps(cls, steps: list[list[Any]]) -> list[list[Any]]:
        for n, step in enumerate(steps):
            if not step or step[0] not in ACTIONS:
                raise ValueError(f"Step {n}: unknown action {step[:1]!r}")
        return steps

    def dump(self) -> dict[str, Any]:
        "Return the record to store; defaults are left out."
        return self.model_dump(exclude_defaults=True)


def is_test_path(path: Path) -> bool:
    "Check whether ``path``, below the code root, points into a snippet's tests."
    return None in path


def _root(path: Path) -> Path:
    return CODE_EXEC_ROOT + path / None


async def get_test(conn: LinkSender, path: Path, case: Path) -> CodeTest:
    "Read test ``case`` of the snippet at ``path``."
    return CodeTest.model_validate(await conn.d_get(_root(path) + case))


async def set_test(conn: LinkSender, path: Path, case: Path, test: CodeTest) -> None:
    "Store test ``case`` of the snippet at ``path``."
    await conn.d_set(_root(path) + case, test.dump())


async def del_test(conn: LinkSender, path: Path, case: Path) -> None:
    "Delete test ``case`` of the snippet at ``path``."
    await conn.d.delete(_root(path) + case)


async def list_tests(conn: LinkSender, path: Path) -> AsyncIterator[tuple[Path, CodeTest]]:
    "Yield the name and content of each test case of the snippet at ``path``."
    async with conn.d_walk(_root(path)) as mon:
        async for case, data in mon:
            if case:
                yield case, CodeTest.model_validate(data)
