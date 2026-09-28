"""
Reading and writing a code snippet together with its test cases.

The exchange format (``moat link code PATH get -r``, ``… import``, and
the files in ``examples/moat-link-job/``) is the snippet's record as
stored (``code``, ``info``, ``vars``, ``default``, ``is_async``, …) plus
one extra key, `TESTS`, which maps each test case's name (a path, in
its string form) to its `CodeTest` record.

Files are named after the snippet's path below the code root, e.g.
``transform.copy.value.yaml``.
"""

from __future__ import annotations

from contextlib import suppress

from moat.lib.path import P, Path
from moat.link.code import CODE_EXEC_ROOT
from moat.link.code.case import CodeTest, list_tests, set_test

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from moat.link.client import LinkSender

__all__ = ["TESTS", "path_from_file", "read_snippet", "split_snippet", "write_snippet"]

TESTS = "tests"
"The key holding the test cases."


def path_from_file(name: str) -> Path:
    "The snippet's path, from a file name like ``…/transform.copy.value.yaml``."
    name = name.rsplit("/", 1)[-1]
    for ext in (".yaml", ".yml"):
        if name.endswith(ext):
            name = name[: -len(ext)]
            break
    return P(name)


def split_snippet(data: Mapping[str, Any]) -> tuple[dict[str, Any], dict[Path, CodeTest]]:
    """
    Split an exchange record into the snippet record and its (validated)
    test cases.
    """
    rec = dict(data)
    tests = rec.pop(TESTS, None) or {}
    if "code" not in rec:
        raise ValueError("The snippet has no 'code'")
    if not isinstance(tests, Mapping):
        raise TypeError(f"'{TESTS}' must be a mapping")
    return rec, {
        (k if isinstance(k, Path) else P(str(k))): CodeTest.model_validate(v)
        for k, v in tests.items()
    }


async def read_snippet(conn: LinkSender, path: Path) -> dict[str, Any]:
    "Read the snippet at ``path``, with its test cases."
    res = dict(await conn.d_get(CODE_EXEC_ROOT + path))
    tests = {}
    with suppress(KeyError):
        async for case, test in list_tests(conn, path):
            tests[str(case)] = test.dump()
    if tests:
        res[TESTS] = tests
    return res


async def write_snippet(conn: LinkSender, path: Path, data: Mapping[str, Any]) -> None:
    """
    Store the snippet at ``path`` and replace its test cases with those
    in ``data``.
    """
    rec, tests = split_snippet(data)
    with suppress(KeyError):
        await conn.d.delete(CODE_EXEC_ROOT + path / None, rec=True)
    await conn.d_set(CODE_EXEC_ROOT + path, rec)
    for case, test in tests.items():
        await set_test(conn, path, case, test)
