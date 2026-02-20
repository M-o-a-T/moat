from __future__ import annotations  # noqa: D100

import pytest

from moat.lib.path import P
from moat.link.code._main import _run_code_test


@pytest.mark.anyio
async def test_code_test_ok():
    "Check code.test execution with args/kw/result."
    data = dict(
        code=dict(
            exec="return left + right",
            vars=["left", "right"],
            test=dict(
                args=[2],
                kw=dict(right=5),
                result=7,
                code="""
assert result == expected
assert await runner(3, right=4) == 7
""",
            ),
        )
    )
    await _run_code_test(data, P("test.code"))


@pytest.mark.anyio
async def test_code_test_bad_result():
    "Check result mismatch reporting for code.test."
    data = dict(
        code=dict(
            exec="return value + 1",
            vars=["value"],
            test=dict(args=[1], result=3),
        )
    )
    with pytest.raises(AssertionError):
        await _run_code_test(data, P("test.code"))
